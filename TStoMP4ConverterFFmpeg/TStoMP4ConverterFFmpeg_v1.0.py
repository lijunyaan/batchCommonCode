import os
import sys
import glob
import time # For small delay in validation
import queue
import threading
import subprocess
import tkinter as tk
from tkinter import filedialog, scrolledtext, messagebox, ttk

# --- 配置 ---
FFMPEG_PATH = "ffmpeg" # 假定 ffmpeg 在系统 PATH 中

# --- 工作线程函数 ---
def convert_files_thread(input_folder_path, output_folder_path, recursive, log_queue):
    """
    在单独的线程中查找 TS 文件并使用 ffmpeg 进行转换。
    """
    log_queue.put(f"输入文件夹: {input_folder_path}\n")
    log_queue.put(f"输出文件夹: {output_folder_path}\n")
    log_queue.put(f"递归搜索: {'是' if recursive else '否'}\n")
    log_queue.put("="*40 + "\n")

    try:
        # 查找 TS 文件
        search_pattern = os.path.join(input_folder_path, '**', '*.ts') if recursive else os.path.join(input_folder_path, '*.ts')
        log_queue.put(f"开始搜索 .ts 文件 (模式: {search_pattern})...\n")
        ts_files = glob.glob(search_pattern, recursive=recursive)

        if not ts_files:
            log_queue.put("错误: 在指定路径及选项下未找到 .ts 文件。\n")
            log_queue.put("<<DONE>>") # 发送完成信号
            return

        log_queue.put(f"找到 {len(ts_files)} 个 .ts 文件。开始转换...\n")
        success_count = 0
        error_count = 0
        skipped_count = 0

        for i, input_file in enumerate(ts_files):
            input_file = os.path.normpath(input_file) # 规范化路径
            base_name = os.path.basename(input_file)
            file_name_without_ext = os.path.splitext(base_name)[0]

            # --- 计算输出文件路径 ---
            relative_path_from_input_base = os.path.relpath(os.path.dirname(input_file), input_folder_path)
            # 如果 relative_path 是 '.', 表示文件在输入文件夹根目录
            if relative_path_from_input_base == ".":
                 output_subfolder = output_folder_path
            else:
                 output_subfolder = os.path.join(output_folder_path, relative_path_from_input_base)

            # 确保输出子目录存在
            try:
                if not os.path.exists(output_subfolder):
                    os.makedirs(output_subfolder)
                    log_queue.put(f"  创建输出子目录: {output_subfolder}\n")
            except OSError as e:
                 log_queue.put(f"错误: 无法创建输出目录 {output_subfolder}: {e}\n")
                 error_count += 1
                 continue # 跳过这个文件

            output_file = os.path.normpath(os.path.join(output_subfolder, f"{file_name_without_ext}.mp4"))

            # --- 检查是否需要转换 ---
            # 可选：如果输出文件已存在且更新时间比输入文件晚，则跳过
            # if os.path.exists(output_file) and os.path.getmtime(output_file) > os.path.getmtime(input_file):
            #     log_queue.put(f"\n--- [{i+1}/{len(ts_files)}] 跳过 (已是最新): {base_name} ---\n")
            #     skipped_count += 1
            #     continue

            log_queue.put(f"\n--- [{i+1}/{len(ts_files)}] 开始转换: {base_name} ---\n")
            log_queue.put(f"  输入: {input_file}\n")
            log_queue.put(f"  输出: {output_file}\n")

            # 构建 ffmpeg 命令
            command = [
                FFMPEG_PATH,
                "-i", input_file,
                "-map", "0",
                "-c", "copy",
                "-bsf:a", "aac_adtstoasc",
                "-y",             # 覆盖现有文件
                output_file
            ]

            try:
                log_queue.put(f"  执行命令: {' '.join(command)}\n")

                creationflags = 0
                if sys.platform == "win32":
                    creationflags = subprocess.CREATE_NO_WINDOW

                process = subprocess.Popen(
                    command,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True,
                    encoding='utf-8',
                    errors='replace',
                    bufsize=1,
                    universal_newlines=True,
                    creationflags=creationflags
                )

                # 实时读取 ffmpeg 的输出并放入队列
                while True:
                    output_line = process.stdout.readline()
                    error_line = process.stderr.readline() # ffmpeg 经常把进度信息输出到 stderr

                    if output_line:
                        log_queue.put(f"    [ffmpeg stdout] {output_line.strip()}\n")
                    if error_line:
                        log_queue.put(f"    [ffmpeg stderr] {error_line.strip()}\n")

                    if not output_line and not error_line and process.poll() is not None:
                        break

                return_code = process.wait()

                if return_code == 0:
                    log_queue.put(f"  成功: {base_name} -> {os.path.basename(output_file)}\n")
                    success_count += 1
                else:
                    log_queue.put(f"  错误: 转换 {base_name} 时 ffmpeg 返回错误码 {return_code}\n")
                    # 尝试删除可能已创建的不完整输出文件
                    if os.path.exists(output_file):
                        try:
                           os.remove(output_file)
                           log_queue.put(f"    已删除不完整的输出文件: {output_file}\n")
                        except OSError as del_e:
                           log_queue.put(f"    警告: 无法删除不完整的输出文件 {output_file}: {del_e}\n")
                    error_count += 1

            except FileNotFoundError:
                log_queue.put(f"严重错误: 未找到 '{FFMPEG_PATH}'。\n")
                log_queue.put("请确保 ffmpeg 已安装并且其路径已正确配置在脚本中或系统 PATH 环境变量中。\n")
                log_queue.put("<<DONE>>") # 发送完成信号
                return # 中止后续转换
            except Exception as e:
                log_queue.put(f"严重错误: 转换 {base_name} 时发生异常: {e}\n")
                error_count += 1

        log_queue.put("\n--- 转换完成 ---\n")
        log_queue.put(f"总计文件: {len(ts_files)}\n")
        log_queue.put(f"成功转换: {success_count}\n")
        log_queue.put(f"跳过文件: {skipped_count}\n")
        log_queue.put(f"转换失败: {error_count}\n")
        log_queue.put("<<DONE>>") # 发送完成信号

    except Exception as e:
        # 捕获查找文件或准备过程中的其他异常
        log_queue.put(f"\n严重错误: 在准备转换时发生意外错误: {e}\n")
        log_queue.put("<<DONE>>") # 确保发送完成信号


# --- Tkinter GUI 类 ---
class ConverterApp:
    def __init__(self, master):
        self.master = master
        master.title("TS to MP4 Converter (Copy Mode)")
        master.geometry("750x550") # 调整窗口大小

        self.log_queue = queue.Queue()
        self.conversion_thread = None
        self.is_converting = False
        self._input_folder_validated = False
        self._output_folder_validated = False # Track if output has been explicitly validated

        # Configure style
        style = ttk.Style()
        style.theme_use('clam') # Or another theme like 'vista', 'xpnative' on Windows

        # --- Input Folder Selection ---
        input_frame = ttk.LabelFrame(master, text="输入设置", padding="10")
        input_frame.pack(fill=tk.X, padx=10, pady=(10, 5))

        input_folder_label = ttk.Label(input_frame, text="输入文件夹:")
        input_folder_label.grid(row=0, column=0, padx=(0, 5), pady=5, sticky=tk.W)

        self.folder_path_var = tk.StringVar()
        self.input_folder_entry = ttk.Entry(input_frame, textvariable=self.folder_path_var, width=60)
        self.input_folder_entry.grid(row=0, column=1, padx=5, pady=5, sticky=tk.EW)
        self.input_folder_entry.bind("<FocusOut>", self.validate_input_folder_event) # 验证输入
        self.input_folder_entry.bind("<KeyRelease>", self.input_folder_typing) # Detect typing to reset validation state

        self.browse_input_button = ttk.Button(input_frame, text="浏览...", command=self.browse_input_folder)
        self.browse_input_button.grid(row=0, column=2, padx=(5, 0), pady=5)

        # --- Output Folder Selection ---
        output_frame = ttk.LabelFrame(master, text="输出设置", padding="10")
        output_frame.pack(fill=tk.X, padx=10, pady=5)

        output_folder_label = ttk.Label(output_frame, text="输出文件夹:")
        output_folder_label.grid(row=0, column=0, padx=(0, 5), pady=5, sticky=tk.W)

        self.output_folder_path_var = tk.StringVar()
        self.output_folder_entry = ttk.Entry(output_frame, textvariable=self.output_folder_path_var, width=60)
        self.output_folder_entry.grid(row=0, column=1, padx=5, pady=5, sticky=tk.EW)
        self.output_folder_entry.bind("<FocusOut>", self.validate_output_folder_event) # 验证输出
        self.output_folder_entry.bind("<KeyRelease>", self.output_folder_typing) # Detect typing

        self.browse_output_button = ttk.Button(output_frame, text="浏览...", command=self.browse_output_folder)
        self.browse_output_button.grid(row=0, column=2, padx=(5, 0), pady=5)

        self.output_info_label = ttk.Label(output_frame, text="(留空则默认使用输入文件夹)", foreground="gray")
        self.output_info_label.grid(row=1, column=1, padx=5, pady=(0,5), sticky=tk.W)

        input_frame.columnconfigure(1, weight=1) # Make entry expand
        output_frame.columnconfigure(1, weight=1) # Make entry expand

        # --- Options and Controls ---
        control_frame = ttk.Frame(master, padding="10")
        control_frame.pack(fill=tk.X, padx=10, pady=5)

        self.recursive_var = tk.BooleanVar(value=False) # Default to non-recursive
        self.recursive_check = ttk.Checkbutton(control_frame, text="递归搜索子文件夹", variable=self.recursive_var)
        self.recursive_check.pack(side=tk.LEFT, padx=(0, 20))

        self.start_button = ttk.Button(control_frame, text="开始转换", command=self.start_conversion)
        self.start_button.pack(side=tk.LEFT)
        self.start_button.state(['disabled']) # Initially disabled until paths are valid

        # --- Log Display ---
        log_frame = ttk.LabelFrame(master, text="转换日志", padding="10")
        log_frame.pack(expand=True, fill=tk.BOTH, padx=10, pady=(5, 10))

        self.log_text = scrolledtext.ScrolledText(log_frame, wrap=tk.WORD, height=15, state='disabled', font=("Consolas", 9)) # Use monospaced font for logs
        self.log_text.pack(expand=True, fill=tk.BOTH, pady=(5,0))
        # Add tags for coloring log messages (optional)
        self.log_text.tag_configure("info", foreground="black")
        self.log_text.tag_configure("error", foreground="red")
        self.log_text.tag_configure("success", foreground="green")
        self.log_text.tag_configure("warning", foreground="orange")
        self.log_text.tag_configure("command", foreground="blue")
        self.log_text.tag_configure("ffmpeg_stderr", foreground="#888888") # Gray for stderr
        self.log_text.tag_configure("header", foreground="purple", font=("Consolas", 9, "bold"))


        # Start checking the log queue
        self.master.after(100, self.process_log_queue)
        # Handle window close event
        self.master.protocol("WM_DELETE_WINDOW", self.on_closing)

        # Initial validation check (in case user previously entered paths)
        self.validate_paths_and_update_start_button()

    def log_message(self, message, tags=None):
        """向日志文本区域添加消息, 可选应用 tag 样式"""
        if tags is None:
            tags = ("info",)
        # Heuristic tag assignment based on content
        if message.startswith("错误:") or message.startswith("严重错误:"):
             tags = ("error",)
        elif message.startswith("成功:"):
             tags = ("success",)
        elif message.startswith("警告:"):
            tags = ("warning",)
        elif "执行命令:" in message:
             tags = ("command",)
        elif "[ffmpeg stderr]" in message:
             tags = ("ffmpeg_stderr",)
        elif message.startswith("---") or message.startswith("==="):
             tags = ("header",)


        self.log_text.config(state='normal') # 启用编辑
        self.log_text.insert(tk.END, message, tags)
        self.log_text.see(tk.END) # 自动滚动到底部
        self.log_text.config(state='disabled') # 禁用编辑


    def browse_input_folder(self):
        """打开文件夹选择对话框并更新输入路径"""
        folder_selected = filedialog.askdirectory()
        if folder_selected:
            self.folder_path_var.set(os.path.normpath(folder_selected))
            self.validate_input_folder_event() # Trigger validation after selection

    def browse_output_folder(self):
        """打开文件夹选择对话框并更新输出路径"""
        folder_selected = filedialog.askdirectory()
        if folder_selected:
            self.output_folder_path_var.set(os.path.normpath(folder_selected))
            self.validate_output_folder_event() # Trigger validation after selection

    def input_folder_typing(self, event=None):
        """Called when user types in the input folder entry."""
        self._input_folder_validated = False
        self.validate_paths_and_update_start_button()

    def output_folder_typing(self, event=None):
        """Called when user types in the output folder entry."""
        self._output_folder_validated = False # Needs revalidation
        self.validate_paths_and_update_start_button()

    def validate_input_folder_event(self, event=None):
        """验证输入文件夹路径 (事件触发)"""
        # Add a small delay to allow paste to settle, maybe not needed
        # self.master.after(50, self._validate_input_folder)
        self._validate_input_folder()


    def _validate_input_folder(self):
        """实际的输入文件夹验证逻辑"""
        path = self.folder_path_var.get().strip()
        is_valid = False
        if path and os.path.isdir(path):
            normalized_path = os.path.normpath(path)
            self.folder_path_var.set(normalized_path) # Update with normalized path
            # 如果输出文件夹为空 或之前等于旧的输入文件夹, 则自动更新输出文件夹
            current_output = self.output_folder_path_var.get().strip()
            if not current_output or not self._output_folder_validated:
                 self.output_folder_path_var.set(normalized_path)
                 self._output_folder_validated = True # Consider it validated if defaulted
            self.input_folder_entry.config(foreground="black")
            self._input_folder_validated = True
            is_valid = True
            # self.log_message(f"输入文件夹有效: {normalized_path}\n")
        elif path: # Path is entered but not a valid directory
            self.input_folder_entry.config(foreground="red")
            self._input_folder_validated = False
            # self.log_message(f"输入文件夹无效或不存在: {path}\n", ("warning",))
        else: # Path is empty
            self.input_folder_entry.config(foreground="black") # Reset color
            self._input_folder_validated = False

        self.validate_paths_and_update_start_button()
        return is_valid

    def validate_output_folder_event(self, event=None):
        """验证输出文件夹路径 (事件触发)"""
        # self.master.after(50, self._validate_output_folder)
        self._validate_output_folder()

    def _validate_output_folder(self):
        """实际的输出文件夹验证逻辑"""
        path = self.output_folder_path_var.get().strip()
        is_valid = False
        if path and os.path.isdir(path):
             normalized_path = os.path.normpath(path)
             self.output_folder_path_var.set(normalized_path)
             self.output_folder_entry.config(foreground="black")
             self._output_folder_validated = True
             is_valid = True
             # self.log_message(f"输出文件夹有效: {normalized_path}\n")
        elif path: # Path is entered but not a valid directory
            self.output_folder_entry.config(foreground="red")
            self._output_folder_validated = False # Mark as explicitly invalid
            # self.log_message(f"输出文件夹无效或不存在: {path}\n", ("warning",))
        else: # Path is empty (will default to input, so considered valid for starting)
             self.output_folder_entry.config(foreground="black") # Reset color
             self._output_folder_validated = False # Reset validation state, rely on start_conversion logic
             is_valid = True # Allow starting even if empty

        self.validate_paths_and_update_start_button()
        return is_valid

    def validate_paths_and_update_start_button(self):
         """检查路径是否有效并启用/禁用开始按钮"""
         input_ok = self._input_folder_validated
         output_path = self.output_folder_path_var.get().strip()
         # Output is OK if it's explicitly validated OR if it's empty (will default)
         output_ok = self._output_folder_validated or not output_path

         if input_ok and output_ok and not self.is_converting:
             self.start_button.state(['!disabled'])
         else:
             self.start_button.state(['disabled'])


    def start_conversion(self):
        """开始转换过程"""
        if self.is_converting:
            messagebox.showwarning("正在进行", "转换已经在进行中。")
            return

        # --- Final Validation Before Starting ---
        if not self._validate_input_folder():
             messagebox.showerror("错误", "输入的文件夹路径无效或不存在。请修正。")
             return

        input_folder = self.folder_path_var.get() # Already normalized
        output_folder = self.output_folder_path_var.get().strip()

        if not output_folder: # Output is empty, default to input
            output_folder = input_folder
            self.output_folder_path_var.set(output_folder) # Update UI
            self.log_message(f"输出文件夹未指定，将使用输入文件夹: {output_folder}\n", ("warning",))
            self._output_folder_validated = True # Mark as validated (defaulted)
        elif not os.path.isdir(output_folder): # Output is specified but invalid
             messagebox.showerror("错误", f"指定的输出文件夹路径无效或不存在: {output_folder}。请修正或留空以使用输入文件夹。")
             self.output_folder_entry.config(foreground="red")
             self._output_folder_validated = False
             self.validate_paths_and_update_start_button() # Disable start button
             return
        else:
             # Ensure output path is normalized if entered manually and validated
             output_folder = os.path.normpath(output_folder)
             self.output_folder_path_var.set(output_folder)


        # --- Check FFmpeg ---
        try:
            ffmpeg_check_flags = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0
            subprocess.run([FFMPEG_PATH, "-version"], check=True, capture_output=True, creationflags=ffmpeg_check_flags)
        except (FileNotFoundError, subprocess.CalledProcessError) as e:
             messagebox.showerror("FFmpeg 错误", f"无法执行 '{FFMPEG_PATH}'。\n请确保 ffmpeg 已安装并且路径配置正确。\n错误详情: {e}")
             self.log_message(f"错误: 无法执行 '{FFMPEG_PATH}'. 请检查安装和路径。\n", ("error",))
             return

        # --- Start Thread ---
        self.is_converting = True
        self.set_ui_state(tk.DISABLED) # Disable controls
        self.start_button.state(['disabled']) # Ensure start button is disabled

        self.log_text.config(state='normal')
        self.log_text.delete('1.0', tk.END) # Clear log
        self.log_text.config(state='disabled')
        # self.log_message(f"开始转换...\n", ("header",))

        recursive = self.recursive_var.get()

        # 创建并启动工作线程
        self.conversion_thread = threading.Thread(
            target=convert_files_thread,
            args=(input_folder, output_folder, recursive, self.log_queue),
            daemon=True
        )
        self.conversion_thread.start()


    def process_log_queue(self):
        """定期检查日志队列并将消息显示在文本区域"""
        try:
            while True: # 处理队列中的所有当前消息
                msg = self.log_queue.get_nowait()
                if msg == "<<DONE>>":
                    # 收到完成信号
                    if self.is_converting: # 确保是在转换过程中完成的
                        self.is_converting = False
                        self.set_ui_state(tk.NORMAL) # 重新启用控件
                        self.validate_paths_and_update_start_button() # Re-evaluate start button state
                        messagebox.showinfo("完成", "转换过程已结束。请查看日志了解详情。")
                else:
                    self.log_message(msg) # Log message with potential coloring
        except queue.Empty:
            pass # 队列为空，什么也不做
        finally:
            # 无论如何，都安排下一次检查
            self.master.after(100, self.process_log_queue)

    def set_ui_state(self, state):
        """启用或禁用界面上的控件"""
        widgets_to_toggle = [
            self.input_folder_entry, self.browse_input_button,
            self.output_folder_entry, self.browse_output_button,
            self.recursive_check, self.start_button
        ]
        for widget in widgets_to_toggle:
            # For ttk widgets, use state()
            if isinstance(widget, ttk.Entry) or isinstance(widget, ttk.Checkbutton) or isinstance(widget, ttk.Button):
                 current_state = widget.state()
                 if state == tk.DISABLED:
                      widget.state(['disabled'])
                 else: # tk.NORMAL
                      # Checkbutton might need special handling if you want to preserve 'selected' state
                      if isinstance(widget, ttk.Checkbutton):
                           widget.state(['!disabled'])
                      # Buttons/Entries can be simplified
                      else:
                           widget.state(['!disabled'])
                           # Re-validate start button explicitly after enabling UI
                           if widget == self.start_button:
                               self.validate_paths_and_update_start_button()


    def on_closing(self):
        """处理窗口关闭事件"""
        if self.is_converting:
            if messagebox.askyesno("确认退出", "转换仍在进行中。确定要退出吗？未完成的转换将被中断。"):
                # Ideally, signal the thread to stop, but Popen needs process.terminate() or process.kill()
                # Since it's a daemon thread, destroying the main window will exit.
                self.master.destroy()
            else:
                return # 用户取消退出
        else:
            self.master.destroy()

# --- 主程序入口 ---
if __name__ == "__main__":
    # print(f"Python version: {sys.version}")
    # print(f"Tkinter version: {tk.TkVersion}")
    root = tk.Tk()
    app = ConverterApp(root)
    root.mainloop()
