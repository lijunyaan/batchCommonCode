import os
import sys
import glob
import time # For small delay in validation
import queue
import threading
import subprocess
import tkinter as tk
from tkinter import filedialog, scrolledtext, messagebox, ttk
import signal # For cancellation

# --- 配置 ---
"""
PyInstaller --onefile --noconsole --icon=app.ico TStoMP4ConverterFFmpeg_v1.1.py
"""
FFMPEG_PATH = "ffmpeg" # 假定 ffmpeg 在系统 PATH 中

# --- 工作线程函数 ---
def convert_files_thread(input_folder_path, output_folder_path, recursive, log_queue, pause_event, cancel_event):
    """
    在单独的线程中查找 TS 文件并使用 ffmpeg 进行转换。
    支持暂停 (在文件之间) 和取消。
    """
    log_queue.put(f"输入文件夹: {input_folder_path}\n")
    log_queue.put(f"输出文件夹: {output_folder_path}\n")
    log_queue.put(f"递归搜索: {'是' if recursive else '否'}\n")
    log_queue.put("="*40 + "\n")

    try:
        search_pattern = os.path.join(input_folder_path, '**', '*.ts') if recursive else os.path.join(input_folder_path, '*.ts')
        log_queue.put(f"开始搜索 .ts 文件 (模式: {search_pattern})...\n")
        ts_files = glob.glob(search_pattern, recursive=recursive)

        if not ts_files:
            log_queue.put("错误: 在指定路径及选项下未找到 .ts 文件。\n")
            log_queue.put("<<DONE>>")
            return

        log_queue.put(f"找到 {len(ts_files)} 个 .ts 文件。开始转换...\n")
        success_count = 0
        error_count = 0
        skipped_count = 0 # Currently not used, but can be for "already exists and newer" logic

        for i, input_file_path in enumerate(ts_files):
            if cancel_event.is_set():
                log_queue.put("\n--- 用户取消了转换 ---\n")
                break

            # --- 暂停点 ---
            if pause_event.is_set():
                log_queue.put(f"\n--- 转换已暂停 (等待文件: {os.path.basename(input_file_path)})。点击 '恢复' 继续。 ---\n")
                pause_event.wait() # 线程将在此阻塞，直到 pause_event.clear() 被调用
                if cancel_event.is_set(): # 检查暂停后是否被取消
                    log_queue.put("\n--- 用户在暂停期间取消了转换 ---\n")
                    break
                log_queue.put(f"\n--- 转换已恢复。继续处理: {os.path.basename(input_file_path)} ---\n")


            input_file_path = os.path.normpath(input_file_path)
            base_name = os.path.basename(input_file_path)
            file_name_without_ext = os.path.splitext(base_name)[0]

            # --- 计算输出文件路径 ---
            # input_folder_path 是搜索的根
            # os.path.dirname(input_file_path) 是当前文件的实际目录
            relative_dir = os.path.relpath(os.path.dirname(input_file_path), input_folder_path)

            if relative_dir == ".": # 文件在输入文件夹的根目录
                output_subfolder_for_file = output_folder_path
            else: # 文件在子目录中
                output_subfolder_for_file = os.path.join(output_folder_path, relative_dir)

            # 确保输出子目录存在
            try:
                if not os.path.exists(output_subfolder_for_file):
                    os.makedirs(output_subfolder_for_file, exist_ok=True) # exist_ok=True避免并发问题
                    log_queue.put(f"  创建输出子目录: {output_subfolder_for_file}\n")
            except OSError as e:
                log_queue.put(f"错误: 无法创建输出目录 {output_subfolder_for_file}: {e}\n")
                error_count += 1
                continue

            output_file_path = os.path.normpath(os.path.join(output_subfolder_for_file, f"{file_name_without_ext}.mp4"))

            log_queue.put(f"\n--- [{i+1}/{len(ts_files)}] 开始转换: {base_name} ---\n")
            log_queue.put(f"  输入: {input_file_path}\n")
            log_queue.put(f"  输出: {output_file_path}\n")

            command = [
                FFMPEG_PATH,
                "-i", input_file_path,
                "-map", "0",        # 映射所有流
                "-c", "copy",       # 直接复制流，不重新编码
                "-bsf:a", "aac_adtstoasc", # 如果音频是 AAC ADTS，转换为 MPEG-4 ADSC
                "-y",               # 无需确认覆盖输出文件
                output_file_path
            ]

            process = None # Initialize process variable
            try:
                log_queue.put(f"  执行命令: {' '.join(command)}\n")

                creationflags = 0
                if sys.platform == "win32":
                    creationflags = subprocess.CREATE_NO_WINDOW # 不显示控制台窗口

                process = subprocess.Popen(
                    command,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True,
                    encoding='utf-8', # Or use system default if issues with specific ffmpeg builds
                    errors='replace', # 处理潜在的编码错误
                    bufsize=1,        # 行缓冲
                    universal_newlines=True, # 兼容不同平台的换行符
                    creationflags=creationflags
                )

                # 实时读取 ffmpeg 的输出并放入队列
                # stdout_reader = threading.Thread(target=stream_reader, args=(process.stdout, log_queue, "[ffmpeg stdout]"))
                # stderr_reader = threading.Thread(target=stream_reader, args=(process.stderr, log_queue, "[ffmpeg stderr]"))
                # stdout_reader.start()
                # stderr_reader.start()

                # Simpler inline reading for now, can be refactored to threads if more complex handling needed
                while True:
                    if cancel_event.is_set() and process:
                        log_queue.put(f"    尝试终止 ffmpeg 进程 (PID: {process.pid})...\n")
                        process.terminate() # SIGTERM
                        try:
                            process.wait(timeout=5) # 等待一段时间让其终止
                        except subprocess.TimeoutExpired:
                            log_queue.put(f"    ffmpeg 进程 (PID: {process.pid}) 未在5秒内终止，强制终止。\n")
                            process.kill() # SIGKILL
                        break # 退出读取循环

                    output_line = process.stdout.readline() if process.stdout else ""
                    error_line = process.stderr.readline() if process.stderr else "" # ffmpeg 经常把进度信息输出到 stderr

                    if output_line:
                        log_queue.put(f"    [ffmpeg stdout] {output_line.strip()}\n")
                    if error_line:
                        log_queue.put(f"    [ffmpeg stderr] {error_line.strip()}\n") # ffmpeg often uses stderr for progress

                    if not output_line and not error_line and process.poll() is not None:
                        break # ffmpeg 进程已结束

                return_code = process.wait() # 获取最终返回码

                if cancel_event.is_set(): # 如果在ffmpeg运行时取消了
                    log_queue.put(f"  转换被取消: {base_name}\n")
                    if os.path.exists(output_file_path): # 清理部分转换的文件
                        try:
                            os.remove(output_file_path)
                            log_queue.put(f"    已删除部分转换的文件: {output_file_path}\n")
                        except OSError as del_e:
                            log_queue.put(f"    警告: 无法删除部分转换的文件 {output_file_path}: {del_e}\n")
                    # error_count += 1 # Or a new "cancelled_count"
                    continue


                if return_code == 0:
                    log_queue.put(f"  成功: {base_name} -> {os.path.basename(output_file_path)}\n")
                    success_count += 1
                else:
                    log_queue.put(f"  错误: 转换 {base_name} 时 ffmpeg 返回错误码 {return_code}\n")
                    if os.path.exists(output_file_path): # 尝试删除不完整的输出文件
                        try:
                           os.remove(output_file_path)
                           log_queue.put(f"    已删除不完整的输出文件: {output_file_path}\n")
                        except OSError as del_e:
                           log_queue.put(f"    警告: 无法删除不完整的输出文件 {output_file_path}: {del_e}\n")
                    error_count += 1

            except FileNotFoundError:
                log_queue.put(f"严重错误: 未找到 '{FFMPEG_PATH}'。\n")
                log_queue.put("请确保 ffmpeg 已安装并且其路径已正确配置在脚本中或系统 PATH 环境变量中。\n")
                log_queue.put("<<DONE>>")
                return # 中止后续转换
            except Exception as e:
                log_queue.put(f"严重错误: 转换 {base_name} 时发生异常: {e}\n")
                if process and process.poll() is None: # 如果ffmpeg仍在运行，尝试终止它
                    process.kill()
                error_count += 1
                if cancel_event.is_set(): break # 如果是取消操作引发的异常，则跳出主循环

        log_queue.put("\n--- 转换操作结束 ---\n")
        if cancel_event.is_set() and not i == len(ts_files)-1 : # If cancelled before all files processed
             log_queue.put("操作被用户提前取消。\n")
        log_queue.put(f"总计文件找到: {len(ts_files)}\n")
        log_queue.put(f"成功转换: {success_count}\n")
        log_queue.put(f"跳过文件: {skipped_count}\n") # Implement skip logic if needed
        log_queue.put(f"转换失败: {error_count}\n")
        log_queue.put("<<DONE>>")

    except Exception as e:
        log_queue.put(f"\n严重错误: 在准备或执行转换时发生意外错误: {e}\n")
        import traceback
        log_queue.put(traceback.format_exc() + "\n")
        log_queue.put("<<DONE>>")


# --- Tkinter GUI 类 ---
class ConverterApp:
    def __init__(self, master):
        self.master = master
        master.title("TS to MP4 Converter (Copy Mode)")
        master.geometry("800x600") # 调整窗口大小

        self.log_queue = queue.Queue()
        self.conversion_thread = None
        self.is_converting = False
        self.is_paused = False
        self.pause_event = threading.Event() # Initially not set (not paused)
        self.cancel_event = threading.Event() # Initially not set (not cancelled)

        self._input_folder_validated = False
        self._output_folder_validated = False

        style = ttk.Style()
        try:
            style.theme_use('clam') # Or 'vista', 'xpnative', 'aqua'
        except tk.TclError:
            print("Clam theme not available, using default.")


        input_frame = ttk.LabelFrame(master, text="输入设置", padding="10")
        input_frame.pack(fill=tk.X, padx=10, pady=(10, 5))
        input_folder_label = ttk.Label(input_frame, text="输入文件夹:")
        input_folder_label.grid(row=0, column=0, padx=(0, 5), pady=5, sticky=tk.W)
        self.folder_path_var = tk.StringVar()
        self.input_folder_entry = ttk.Entry(input_frame, textvariable=self.folder_path_var, width=60)
        self.input_folder_entry.grid(row=0, column=1, padx=5, pady=5, sticky=tk.EW)
        self.input_folder_entry.bind("<FocusOut>", self.validate_input_folder_event)
        self.input_folder_entry.bind("<KeyRelease>", self.input_folder_typing)
        self.browse_input_button = ttk.Button(input_frame, text="浏览...", command=self.browse_input_folder)
        self.browse_input_button.grid(row=0, column=2, padx=(5, 0), pady=5)
        input_frame.columnconfigure(1, weight=1)

        output_frame = ttk.LabelFrame(master, text="输出设置", padding="10")
        output_frame.pack(fill=tk.X, padx=10, pady=5)
        output_folder_label = ttk.Label(output_frame, text="输出文件夹:")
        output_folder_label.grid(row=0, column=0, padx=(0, 5), pady=5, sticky=tk.W)
        self.output_folder_path_var = tk.StringVar()
        self.output_folder_entry = ttk.Entry(output_frame, textvariable=self.output_folder_path_var, width=60)
        self.output_folder_entry.grid(row=0, column=1, padx=5, pady=5, sticky=tk.EW)
        self.output_folder_entry.bind("<FocusOut>", self.validate_output_folder_event)
        self.output_folder_entry.bind("<KeyRelease>", self.output_folder_typing)
        self.browse_output_button = ttk.Button(output_frame, text="浏览...", command=self.browse_output_folder)
        self.browse_output_button.grid(row=0, column=2, padx=(5, 0), pady=5)
        self.output_info_label = ttk.Label(output_frame, text="(留空则默认使用与输入文件夹相同的目录结构)", foreground="gray")
        self.output_info_label.grid(row=1, column=1, padx=5, pady=(0,5), sticky=tk.W)
        output_frame.columnconfigure(1, weight=1)

        control_frame = ttk.Frame(master, padding="10")
        control_frame.pack(fill=tk.X, padx=10, pady=5)
        self.recursive_var = tk.BooleanVar(value=False)
        self.recursive_check = ttk.Checkbutton(control_frame, text="递归搜索子文件夹", variable=self.recursive_var)
        self.recursive_check.pack(side=tk.LEFT, padx=(0, 10))

        self.start_button = ttk.Button(control_frame, text="开始转换", command=self.start_conversion)
        self.start_button.pack(side=tk.LEFT, padx=5)
        self.start_button.state(['disabled'])

        self.pause_resume_button = ttk.Button(control_frame, text="暂停", command=self.toggle_pause_resume)
        self.pause_resume_button.pack(side=tk.LEFT, padx=5)
        self.pause_resume_button.state(['disabled'])

        self.cancel_button = ttk.Button(control_frame, text="取消转换", command=self.cancel_conversion)
        self.cancel_button.pack(side=tk.LEFT, padx=5)
        self.cancel_button.state(['disabled'])


        log_frame = ttk.LabelFrame(master, text="转换日志", padding="10")
        log_frame.pack(expand=True, fill=tk.BOTH, padx=10, pady=(5, 10))
        self.log_text = scrolledtext.ScrolledText(log_frame, wrap=tk.WORD, height=15, state='disabled', font=("Consolas", 9))
        self.log_text.pack(expand=True, fill=tk.BOTH, pady=(5,0))
        self.log_text.tag_configure("info", foreground="black")
        self.log_text.tag_configure("error", foreground="red", font=("Consolas", 9, "bold"))
        self.log_text.tag_configure("success", foreground="green")
        self.log_text.tag_configure("warning", foreground="orange")
        self.log_text.tag_configure("command", foreground="blue")
        self.log_text.tag_configure("ffmpeg_stderr", foreground="#777777") # Lighter gray
        self.log_text.tag_configure("header", foreground="purple", font=("Consolas", 9, "bold"))

        self.master.after(100, self.process_log_queue)
        self.master.protocol("WM_DELETE_WINDOW", self.on_closing)
        self.validate_paths_and_update_start_button()

    def log_message(self, message, tags=None):
        """向日志文本区域添加消息, 可选应用 tag 样式"""
        final_tags = ("info",) # Default
        if isinstance(tags, str): tags = (tags,) # Ensure tags is a tuple

        if tags:
            final_tags = tags
        else: # Heuristic tag assignment based on content
            if message.startswith("错误:") or message.startswith("严重错误:"): final_tags = ("error",)
            elif message.startswith("成功:"): final_tags = ("success",)
            elif message.startswith("警告:"): final_tags = ("warning",)
            elif "执行命令:" in message or "ffmpeg version" in message : final_tags = ("command",)
            elif "[ffmpeg stderr]" in message: final_tags = ("ffmpeg_stderr",)
            elif message.startswith("---") or message.startswith("===") or "输入文件夹:" in message or "输出文件夹:" in message: final_tags = ("header",)

        self.log_text.config(state='normal')
        self.log_text.insert(tk.END, message, final_tags)
        self.log_text.see(tk.END)
        self.log_text.config(state='disabled')

    def browse_input_folder(self):
        folder_selected = filedialog.askdirectory()
        if folder_selected:
            self.folder_path_var.set(os.path.normpath(folder_selected))
            self.validate_input_folder_event()

    def browse_output_folder(self):
        folder_selected = filedialog.askdirectory()
        if folder_selected:
            self.output_folder_path_var.set(os.path.normpath(folder_selected))
            self.validate_output_folder_event()

    def input_folder_typing(self, event=None):
        self._input_folder_validated = False
        self.validate_paths_and_update_start_button()

    def output_folder_typing(self, event=None):
        self._output_folder_validated = False
        self.validate_paths_and_update_start_button()

    def validate_input_folder_event(self, event=None):
        self._validate_input_folder()

    def _validate_input_folder(self):
        path = self.folder_path_var.get().strip()
        is_valid = False
        if path and os.path.isdir(path):
            normalized_path = os.path.normpath(path)
            self.folder_path_var.set(normalized_path)
            current_output = self.output_folder_path_var.get().strip()
            if not current_output or not self._output_folder_validated:
                 self.output_folder_path_var.set(normalized_path)
                 self._output_folder_validated = True # Implicitly validated if defaulted
            self.input_folder_entry.config(foreground="black")
            self._input_folder_validated = True
            is_valid = True
        elif path:
            self.input_folder_entry.config(foreground="red")
            self._input_folder_validated = False
        else:
            self.input_folder_entry.config(foreground="black")
            self._input_folder_validated = False
        self.validate_paths_and_update_start_button()
        return is_valid

    def validate_output_folder_event(self, event=None):
        self._validate_output_folder()

    def _validate_output_folder(self):
        path = self.output_folder_path_var.get().strip()
        is_valid = False
        if path and os.path.isdir(path):
             normalized_path = os.path.normpath(path)
             self.output_folder_path_var.set(normalized_path)
             self.output_folder_entry.config(foreground="black")
             self._output_folder_validated = True
             is_valid = True
        elif path:
            self.output_folder_entry.config(foreground="red")
            self._output_folder_validated = False
        else:
             self.output_folder_entry.config(foreground="black")
             self._output_folder_validated = False # Will default, so considered ok for starting
             is_valid = True
        self.validate_paths_and_update_start_button()
        return is_valid

    def validate_paths_and_update_start_button(self):
         input_ok = self._input_folder_validated
         output_path = self.output_folder_path_var.get().strip()
         output_ok = self._output_folder_validated or not output_path # OK if validated or empty (will default)

         if input_ok and output_ok and not self.is_converting:
             self.start_button.state(['!disabled'])
         else:
             self.start_button.state(['disabled'])
         # Pause/Cancel buttons depend on is_converting state, handled elsewhere

    def start_conversion(self):
        if self.is_converting:
            messagebox.showwarning("正在进行", "转换已经在进行中。")
            return

        if not self._validate_input_folder():
             messagebox.showerror("错误", "输入的文件夹路径无效或不存在。请修正。")
             return

        input_folder = self.folder_path_var.get()
        output_folder = self.output_folder_path_var.get().strip()

        if not output_folder:
            output_folder = input_folder
            self.output_folder_path_var.set(output_folder)
            self.log_message(f"输出文件夹未指定，将使用输入文件夹作为基础: {output_folder}\n", ("warning",))
            self._output_folder_validated = True
        elif not os.path.isdir(output_folder):
             messagebox.showerror("错误", f"指定的输出文件夹路径无效或不存在: {output_folder}。请修正或留空。")
             self.output_folder_entry.config(foreground="red")
             self._output_folder_validated = False
             self.validate_paths_and_update_start_button()
             return
        else:
             output_folder = os.path.normpath(output_folder)
             self.output_folder_path_var.set(output_folder)

        try:
            ffmpeg_check_flags = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0
            result = subprocess.run([FFMPEG_PATH, "-version"], check=True, capture_output=True, text=True, creationflags=ffmpeg_check_flags)
            self.log_message(f"FFmpeg 版本信息:\n{result.stdout.splitlines()[0]}\n", ("info",)) # Log first line of version
        except (FileNotFoundError, subprocess.CalledProcessError) as e:
             messagebox.showerror("FFmpeg 错误", f"无法执行 '{FFMPEG_PATH}'。\n请确保 ffmpeg 已安装并且路径配置正确。\n错误详情: {e}")
             self.log_message(f"错误: 无法执行 '{FFMPEG_PATH}'. 请检查安装和路径。\n", ("error",))
             return

        self.is_converting = True
        self.is_paused = False
        self.pause_event.clear() # Ensure not paused at start
        self.cancel_event.clear() # Ensure not cancelled at start

        self.set_ui_state_for_conversion(True)

        self.log_text.config(state='normal')
        self.log_text.delete('1.0', tk.END)
        self.log_text.config(state='disabled')

        recursive = self.recursive_var.get()
        self.conversion_thread = threading.Thread(
            target=convert_files_thread,
            args=(input_folder, output_folder, recursive, self.log_queue, self.pause_event, self.cancel_event),
            daemon=True
        )
        self.conversion_thread.start()

    def toggle_pause_resume(self):
        if not self.is_converting: return

        if self.is_paused: # Currently paused, so resume
            self.is_paused = False
            self.pause_event.clear() # Allow worker thread to proceed
            self.pause_resume_button.config(text="暂停")
            self.log_message("--- 转换已手动恢复 ---\n", ("info",))
        else: # Currently running, so pause
            self.is_paused = True
            self.pause_event.set() # Signal worker thread to pause
            self.pause_resume_button.config(text="恢复")
            self.log_message("--- 转换已手动暂停 (将在当前文件完成后生效) ---\n", ("warning",))

    def cancel_conversion(self):
        if not self.is_converting: return

        if messagebox.askyesno("确认取消", "确定要取消当前的转换操作吗？"):
            self.cancel_event.set() # Signal thread to cancel
            if self.is_paused: # If paused, also clear pause event to let thread process cancel
                self.pause_event.clear()
            self.log_message("\n--- 用户请求取消转换... ---\n", ("warning",))
            # UI state will be reset when <<DONE>> is received and cancel_event is checked

    def process_log_queue(self):
        try:
            while True:
                msg = self.log_queue.get_nowait()
                if msg == "<<DONE>>":
                    if self.is_converting or self.cancel_event.is_set(): # Handle normal finish or cancelled finish
                        self.is_converting = False
                        self.is_paused = False # Reset pause state
                        self.set_ui_state_for_conversion(False)
                        if not self.cancel_event.is_set(): # Only show "completed" if not cancelled
                            messagebox.showinfo("完成", "转换过程已结束。请查看日志了解详情。")
                        else:
                            messagebox.showinfo("已取消", "转换操作已被取消。")
                        # self.cancel_event.clear() # Reset for next run, or do it in start_conversion
                else:
                    self.log_message(msg)
        except queue.Empty:
            pass
        finally:
            self.master.after(100, self.process_log_queue)

    def set_ui_state_for_conversion(self, converting):
        """ Helper to manage UI state during conversion """
        if converting:
            self.start_button.state(['disabled'])
            self.pause_resume_button.state(['!disabled'])
            self.pause_resume_button.config(text="暂停")
            self.cancel_button.state(['!disabled'])
            # Disable path entries and browse buttons
            for widget in [self.input_folder_entry, self.browse_input_button,
                           self.output_folder_entry, self.browse_output_button,
                           self.recursive_check]:
                widget.state(['disabled'])
        else: # Not converting (finished or cancelled)
            self.validate_paths_and_update_start_button() # Re-enable start if paths are valid
            self.pause_resume_button.state(['disabled'])
            self.pause_resume_button.config(text="暂停") # Reset text
            self.cancel_button.state(['disabled'])
            # Enable path entries and browse buttons
            for widget in [self.input_folder_entry, self.browse_input_button,
                           self.output_folder_entry, self.browse_output_button,
                           self.recursive_check]:
                widget.state(['!disabled'])

    def on_closing(self):
        if self.is_converting:
            if messagebox.askyesno("确认退出", "转换仍在进行中。确定要退出吗？"):
                self.cancel_event.set() # Signal thread to stop
                if self.is_paused: self.pause_event.clear() # Allow thread to process cancel
                # Wait a very short time for the thread to potentially acknowledge
                if self.conversion_thread and self.conversion_thread.is_alive():
                    self.conversion_thread.join(timeout=0.5) # Brief wait
                self.master.destroy()
            else:
                return
        else:
            self.master.destroy()

if __name__ == "__main__":
    root = tk.Tk()
    app = ConverterApp(root)
    root.mainloop()
