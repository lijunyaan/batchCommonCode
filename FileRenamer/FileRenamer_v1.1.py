import os
import re
import sys
import time
import tkinter as tk
from datetime import datetime
from tkinter import ttk, filedialog, messagebox, scrolledtext, font as tkfont

# --- BEGIN: TkDnD Path Configuration for PyInstaller ---
# This block MUST be before the `tkinterdnd2` import.
if getattr(sys, 'frozen', False) and hasattr(sys, '_MEIPASS'):
    # This code runs when the application is frozen (e.g., by PyInstaller)
    # sys._MEIPASS is the path to the temporary folder where PyInstaller extracts bundled files.
    # We need to tell tkinterdnd2 where to find the tkdnd library files.
    # The destination path in PyInstaller's --add-data should match 'tkinterdnd2/tkdnd' here.
    # e.g., --add-data "/path/to/site-packages/tkinterdnd2/tkdnd:tkinterdnd2/tkdnd"
    tkdnd_path = os.path.join(sys._MEIPASS, 'tkinterdnd2', 'tkdnd')
    os.environ['TKDND_LIBRARY'] = tkdnd_path
# --- END: TkDnD Path Configuration for PyInstaller ---

'''
PyInstaller --onefile --noconsole --icon=app.ico FileRenamer_v1.1.py
PyInstaller --onefile --noconsole --icon=app.ico --add-data "D:\\codework\\batchCommonCode\\.venv\\Lib\\site-packages\\tkinterdnd2\\tkdnd:tkinterdnd2/tkdnd" FileRenamer_v1.1.py

PyInstaller 打包命令示例 (请根据你的环境调整 tkdnd 源码路径):
1. 找到你的 tkinterdnd2 库中的 tkdnd 文件夹路径。
   可以用以下 Python 代码找到它 (确保 tkinterdnd2-universal 已安装):
   import tkinterdnd2, os
   print(os.path.join(os.path.dirname(tkinterdnd2.__file__), 'tkdnd'))
   假设输出是: C:\\Python39\\Lib\\site-packages\\tkinterdnd2\\tkdnd

2. Windows:
   PyInstaller --onefile --noconsole --icon=app.ico --add-data "D:\\codework\\batchCommonCode\\.venv\\Lib\\site-packages\\tkinterdnd2\\tkdnd:tkinterdnd2/tkdnd" FileRenamer_v1.1.py

3. Linux/macOS (路径分隔符不同):
   PyInstaller --onefile --noconsole --add-data "/path/to/your/env/lib/python3.9/site-packages/tkinterdnd2/tkdnd:tkinterdnd2/tkdnd" FileRenamer.py

确保 --add-data 的目标路径是 "tkinterdnd2/tkdnd" (不带前导斜杠),
这与上面代码中 os.path.join(sys._MEIPASS, 'tkinterdnd2', 'tkdnd') 对应。
使用 --windowed 代替 --noconsole 如果你希望完全没有命令行窗口 (通常用于GUI应用)。
'''
# --- Try importing tkinterdnd2 ---
try:
    # 推荐使用 tkinterdnd2-universal: pip install tkinterdnd2-universal
    from tkinterdnd2 import DND_FILES, TkinterDnD
    USE_DND = True
except ImportError:
    USE_DND = False
    print("提示: 未找到 'tkinterdnd2' 库。拖放功能将不可用。")
    print("请尝试安装: pip install tkinterdnd2-universal")
    TkinterDnD = tk # Fallback for Tk() if DnD not available

# --- Constants ---
PREVIEW_SEPARATOR = "  ->  "
DEFAULT_DATE_FORMAT = "%Y%m%d_%H%M%S"

class FileRenamerApp:
    def __init__(self, master):
        self.master = master
        self.master.title("高级文件重命名器 v1.4") # Incremented version
        try:
            self.master.geometry("1000x750")
        except tk.TclError:
            print("无法设置初始窗口大小。")

        self.folder_path = tk.StringVar()
        self.original_files_full_path = []
        self.original_files_display = []
        self.root_folder_for_relative_path = ""

        # --- Font setup ---
        self.default_font = tkfont.nametofont("TkDefaultFont")
        try:
            self.bold_font = tkfont.Font(family=self.default_font.cget("family"), size=self.default_font.cget("size"), weight="bold")
        except tk.TclError:
            self.bold_font = tkfont.Font(font=self.default_font) # Fallback
            self.bold_font.configure(weight='bold')
        self.normal_font = self.default_font

        # --- UI Setup ---
        # Top Frame
        top_frame = ttk.Frame(master, padding="10")
        top_frame.pack(fill=tk.X)

        ttk.Label(top_frame, text="文件夹路径:").pack(side=tk.LEFT, padx=(0, 5))
        self.folder_entry = ttk.Entry(top_frame, textvariable=self.folder_path, width=50)
        self.folder_entry.pack(side=tk.LEFT, expand=True, fill=tk.X, padx=5)
        self.browse_button = ttk.Button(top_frame, text="浏览...", command=self.browse_folder)
        self.browse_button.pack(side=tk.LEFT, padx=5)
        self.recursive_var = tk.BooleanVar(value=False)
        self.recursive_check = ttk.Checkbutton(top_frame, text="包含子文件夹", variable=self.recursive_var, command=self.trigger_reload)
        self.recursive_check.pack(side=tk.LEFT, padx=5)
        ttk.Label(top_frame, text="筛选器(名称包含):").pack(side=tk.LEFT, padx=(10, 5))
        self.filter_var = tk.StringVar()
        self.filter_entry = ttk.Entry(top_frame, textvariable=self.filter_var, width=15)
        self.filter_entry.pack(side=tk.LEFT, padx=5)
        self.filter_entry.bind("<Return>", self.trigger_reload)
        self.filter_entry.bind("<FocusOut>", self.trigger_reload)
        self.load_button = ttk.Button(top_frame, text="加载/刷新", command=self.load_files)
        self.load_button.pack(side=tk.LEFT, padx=5)

        # Middle Frame: Paned Window
        self.paned_window = ttk.PanedWindow(master, orient=tk.HORIZONTAL)
        self.paned_window.pack(fill=tk.BOTH, expand=True, padx=10, pady=(0, 5))

        # Left Pane
        left_pane = ttk.Frame(self.paned_window, padding=(0, 0, 5, 0))
        self.paned_window.add(left_pane, weight=1)
        left_controls = ttk.Frame(left_pane)
        left_controls.pack(fill=tk.X, pady=(0, 5))
        ttk.Label(left_controls, text="原始文件名 (可拖放)").pack(side=tk.LEFT)
        ttk.Button(left_controls, text="清除", command=self.clear_original_list, width=5).pack(side=tk.RIGHT, padx=2)
        ttk.Button(left_controls, text="复制", command=self.copy_original_names, width=5).pack(side=tk.RIGHT)
        self.text_original = scrolledtext.ScrolledText(left_pane, wrap=tk.NONE, width=45, height=20, state=tk.DISABLED)
        self.text_original.pack(fill=tk.BOTH, expand=True)
        self.text_original.tag_configure("odd_row", font=self.bold_font)
        self.text_original.tag_configure("even_row", font=self.normal_font)
        if USE_DND:
            self.text_original.drop_target_register(DND_FILES)
            self.text_original.dnd_bind('<<Drop>>', self.handle_drop)
        else:
             ttk.Label(left_pane, text="(拖放功能不可用)", foreground="grey").pack(fill=tk.X)

        # Right Pane
        right_pane = ttk.Frame(self.paned_window, padding=(5, 0, 0, 0))
        self.paned_window.add(right_pane, weight=1)
        right_pane.grid_columnconfigure(0, weight=1)
        right_pane.grid_rowconfigure(0, weight=1) # Ensure scrolled text expands
        right_controls = ttk.Frame(right_pane)
        right_controls.pack(fill=tk.X, pady=(0, 5))
        ttk.Label(right_controls, text="新文件名 (粘贴或使用下方规则生成/修改)").pack(side=tk.LEFT)
        self.clear_button_right = ttk.Button(right_controls, text="清除", command=lambda: self.text_new.delete('1.0', tk.END), width=5)
        self.clear_button_right.pack(side=tk.RIGHT, padx=2)
        self.paste_button_right = ttk.Button(right_controls, text="粘贴", command=self.paste_to_new_names, width=5)
        self.paste_button_right.pack(side=tk.RIGHT, padx=2)
        self.text_new = scrolledtext.ScrolledText(right_pane, wrap=tk.NONE, width=45, height=20)
        self.text_new.pack(fill=tk.BOTH, expand=True)

        # Rules Frame (Below Paned Window)
        rules_frame = ttk.LabelFrame(master, text="快速修改新文件名列表", padding="10")
        rules_frame.pack(fill=tk.X, padx=10, pady=(5, 5))
        rules_frame.grid_columnconfigure(1, weight=1) # Allow entry to expand
        rules_frame.grid_columnconfigure(4, weight=1) # Allow entry to expand

        # -- Replace Rule --
        ttk.Label(rules_frame, text="查找:").grid(row=0, column=0, padx=5, pady=3, sticky=tk.W)
        self.replace_find_var = tk.StringVar()
        ttk.Entry(rules_frame, textvariable=self.replace_find_var).grid(row=0, column=1, padx=5, pady=3, sticky=tk.EW)
        ttk.Label(rules_frame, text="替换为:").grid(row=1, column=0, padx=5, pady=3, sticky=tk.W)
        self.replace_with_var = tk.StringVar()
        ttk.Entry(rules_frame, textvariable=self.replace_with_var).grid(row=1, column=1, padx=5, pady=3, sticky=tk.EW)
        self.replace_case_var = tk.BooleanVar(value=True)
        ttk.Checkbutton(rules_frame, text="区分大小写", variable=self.replace_case_var).grid(row=0, column=2, padx=5, pady=3, sticky=tk.W)
        ttk.Button(rules_frame, text="应用替换", command=self.apply_replace).grid(row=1, column=2, padx=5, pady=3, sticky=tk.W)

        # -- Insert Rule --
        ttk.Label(rules_frame, text="插入文本:").grid(row=0, column=3, padx=(20, 5), pady=3, sticky=tk.W)
        self.insert_text_var = tk.StringVar()
        ttk.Entry(rules_frame, textvariable=self.insert_text_var).grid(row=0, column=4, padx=5, pady=3, sticky=tk.EW)
        ttk.Label(rules_frame, text="位置:").grid(row=1, column=3, padx=(20, 5), pady=3, sticky=tk.W)
        insert_pos_frame = ttk.Frame(rules_frame)
        insert_pos_frame.grid(row=1, column=4, padx=5, pady=0, sticky=tk.EW)
        self.insert_pos_var = tk.StringVar(value="开头")
        pos_options = ["开头", "结尾", "索引(从0开始)"]
        ttk.Combobox(insert_pos_frame, textvariable=self.insert_pos_var, values=pos_options, state="readonly", width=12).pack(side=tk.LEFT)
        self.insert_index_var = tk.StringVar(value="0")
        ttk.Entry(insert_pos_frame, textvariable=self.insert_index_var, width=4).pack(side=tk.LEFT, padx=(5, 0))
        ttk.Button(rules_frame, text="应用插入", command=self.apply_insert).grid(row=0, column=5, rowspan=2, padx=5, pady=3, sticky=tk.W + tk.S)

        # -- Separator 1 --
        ttk.Separator(rules_frame, orient=tk.HORIZONTAL).grid(row=2, column=0, columnspan=6, sticky=tk.EW, pady=8)

        # -- Sequence Rule --
        ttk.Label(rules_frame, text="插入序号:", font=self.bold_font).grid(row=3, column=0, padx=5, pady=3, sticky=tk.W)
        seq_frame = ttk.Frame(rules_frame)
        seq_frame.grid(row=4, column=0, columnspan=3, sticky=tk.EW, padx=5) # Span 3 columns
        ttk.Label(seq_frame, text="起始:").pack(side=tk.LEFT, padx=(0,2))
        self.seq_start_var = tk.StringVar(value="1")
        ttk.Entry(seq_frame, textvariable=self.seq_start_var, width=5).pack(side=tk.LEFT, padx=(0,10))
        ttk.Label(seq_frame, text="补零宽度:").pack(side=tk.LEFT, padx=(0,2))
        self.seq_pad_var = tk.StringVar(value="0")
        ttk.Entry(seq_frame, textvariable=self.seq_pad_var, width=3).pack(side=tk.LEFT, padx=(0,10))
        ttk.Label(seq_frame, text="前缀:").pack(side=tk.LEFT, padx=(0,2))
        self.seq_prefix_var = tk.StringVar(value="")
        ttk.Entry(seq_frame, textvariable=self.seq_prefix_var, width=6).pack(side=tk.LEFT, padx=(0,10))
        ttk.Label(seq_frame, text="后缀:").pack(side=tk.LEFT, padx=(0,2))
        self.seq_suffix_var = tk.StringVar(value="")
        ttk.Entry(seq_frame, textvariable=self.seq_suffix_var, width=6).pack(side=tk.LEFT)

        ttk.Label(rules_frame, text="位置:").grid(row=5, column=0, padx=5, pady=3, sticky=tk.W)
        seq_pos_frame = ttk.Frame(rules_frame)
        seq_pos_frame.grid(row=5, column=1, columnspan=2, padx=5, pady=0, sticky=tk.EW) # Span 2 columns for entry
        self.seq_pos_var = tk.StringVar(value="开头")
        ttk.Combobox(seq_pos_frame, textvariable=self.seq_pos_var, values=pos_options, state="readonly", width=12).pack(side=tk.LEFT)
        self.seq_index_var = tk.StringVar(value="0")
        ttk.Entry(seq_pos_frame, textvariable=self.seq_index_var, width=4).pack(side=tk.LEFT, padx=(5, 0))
        ttk.Button(rules_frame, text="应用序号", command=self.apply_sequence).grid(row=4, column=3, rowspan=2, padx=(20,5), pady=3, sticky=tk.W + tk.S) # Aligned with Insert button column

        # -- Creation Date Rule --
        ttk.Label(rules_frame, text="创建日期:", font=self.bold_font).grid(row=3, column=4, padx=5, pady=3, sticky=tk.W)
        date_frame = ttk.Frame(rules_frame)
        date_frame.grid(row=4, column=4, columnspan=2, sticky=tk.EW, padx=5) # Span 2 columns
        ttk.Label(date_frame, text="格式:").pack(side=tk.LEFT, padx=(0,2))
        self.date_format_var = tk.StringVar(value=DEFAULT_DATE_FORMAT)
        self.date_format_entry = ttk.Entry(date_frame, textvariable=self.date_format_var, width=18)
        self.date_format_entry.pack(side=tk.LEFT, padx=(0,5)) # Reduced padding
        self.date_format_entry.bind("<KeyRelease>", self._update_date_format_preview)
        self.date_format_preview_label = ttk.Label(date_frame, text="", foreground="grey")
        self.date_format_preview_label.pack(side=tk.LEFT, expand=True, fill=tk.X) # Allow preview to take space
        self._update_date_format_preview()

        date_prefix_suffix_frame = ttk.Frame(rules_frame) # New frame for better alignment
        date_prefix_suffix_frame.grid(row=5, column=4, columnspan=2, sticky=tk.EW, padx=5)
        ttk.Label(date_prefix_suffix_frame, text="前缀:").pack(side=tk.LEFT, padx=(0,2))
        self.date_prefix_var = tk.StringVar(value="")
        ttk.Entry(date_prefix_suffix_frame, textvariable=self.date_prefix_var, width=10).pack(side=tk.LEFT, padx=(0,10))
        ttk.Label(date_prefix_suffix_frame, text="后缀:").pack(side=tk.LEFT, padx=(0,2))
        self.date_suffix_var = tk.StringVar(value="")
        ttk.Entry(date_prefix_suffix_frame, textvariable=self.date_suffix_var, width=10).pack(side=tk.LEFT)

        ttk.Button(rules_frame, text="应用日期", command=self.apply_creation_date).grid(row=6, column=4, columnspan=2, padx=5, pady=5, sticky=tk.W)
        date_info_label = ttk.Label(rules_frame, text="使用 strftime 格式代码 (例如 %Y%m%d_%H%M)。保留原扩展名。", wraplength=350, foreground="grey", justify=tk.LEFT)
        date_info_label.grid(row=7, column=4, columnspan=2, padx=5, pady=(0, 5), sticky=tk.W)


        # Bottom Frame
        bottom_frame = ttk.Frame(master, padding="10")
        bottom_frame.pack(fill=tk.X)
        self.rename_button = ttk.Button(bottom_frame, text="预览并重命名...", command=self.preview_and_rename)
        self.rename_button.pack(side=tk.LEFT, padx=5)
        self.status_var = tk.StringVar()
        self.status_label = ttk.Label(bottom_frame, textvariable=self.status_var, relief=tk.SUNKEN, anchor=tk.W)
        self.status_label.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=5)
        self.status_var.set("请选择文件夹或拖放文件到左侧列表。")

    def browse_folder(self):
        directory = filedialog.askdirectory()
        if directory:
            self.folder_path.set(directory)
            self.load_files()

    def trigger_reload(self, event=None):
        folder = self.folder_path.get()
        if folder and folder != "(多个拖放来源)" and os.path.isdir(folder):
            self.load_files()
        elif folder == "(多个拖放来源)":
            self.status_var.set("选项已更改。请重新拖放文件以应用新设置。")

    def handle_drop(self, event):
        if not USE_DND: return
        raw_data = event.data
        # TkinterDnD on Windows provides paths often in "{C:/path/to/file with space.txt} C:/path/to/another.doc" format
        # or sometimes just space-separated if no spaces in paths.
        # On Linux, it's usually newline-separated.
        # We need to robustly parse this.
        cleaned_data = raw_data.strip('{} ') # Remove leading/trailing braces and spaces

        potential_paths = []
        # First, try to split by newline (common on Linux, or if one path per line)
        if '\n' in cleaned_data:
            potential_paths = [p.strip() for p in cleaned_data.split('\n') if p.strip()]
        else:
            # For Windows-style "{path with spaces} other_path"
            # Regex to find paths enclosed in {} or non-space sequences
            # This regex handles {path with spaces} and "path with spaces" and path_without_spaces
            potential_paths = re.findall(r'\{[^{}]*\}|\"[^"]*\"|\S+', raw_data)
            potential_paths = [p.strip('{} "') for p in potential_paths if p.strip()]


        dropped_files = []
        dropped_folders = []

        for path_str in potential_paths:
             if not path_str: continue # Skip empty strings
             path_str = path_str.strip('"') # Remove quotes if any persist
             # Sometimes paths might be URI encoded (e.g. %20 for space), tkinterdnd2 usually decodes
             # but if not, consider `urllib.parse.unquote`
             if os.path.isfile(path_str):
                 dropped_files.append(os.path.abspath(path_str))
             elif os.path.isdir(path_str):
                 dropped_folders.append(os.path.abspath(path_str))
             else:
                  print(f"Skipping invalid dropped item: {path_str}")


        if not dropped_files and not dropped_folders:
            self.status_var.set("拖放未包含有效的文件或文件夹。")
            return

        # Determine a common root for display, if sensible
        all_paths_for_common = [os.path.dirname(f) for f in dropped_files] + dropped_folders
        if all_paths_for_common:
            try:
                self.root_folder_for_relative_path = os.path.commonpath(all_paths_for_common)
            except ValueError: # Happens if paths are on different drives on Windows
                self.root_folder_for_relative_path = None # Or some other indicator
        else:
            self.root_folder_for_relative_path = None


        self.clear_lists() # Clear original and new names
        self.folder_path.set("(多个拖放来源)") # Indicate drag-drop mode

        all_files_to_load = list(dropped_files) # Start with directly dropped files
        is_recursive = self.recursive_var.get()
        file_filter = self.filter_var.get().lower()

        for folder in dropped_folders:
            current_root_for_walk = folder
            try:
                if is_recursive:
                    for root, _, files in os.walk(current_root_for_walk):
                        for filename in files:
                             if not file_filter or file_filter in filename.lower():
                                full_path = os.path.join(root, filename)
                                all_files_to_load.append(full_path)
                else: # Not recursive, only files directly in the dropped folder
                    for filename in os.listdir(current_root_for_walk):
                        full_path = os.path.join(current_root_for_walk, filename)
                        if os.path.isfile(full_path): # Make sure it's a file
                            if not file_filter or file_filter in filename.lower():
                                all_files_to_load.append(full_path)
            except Exception as e:
                 print(f"Error reading dropped folder {folder}: {e}")
                 self.status_var.set(f"读取文件夹 {os.path.basename(folder)} 时出错, 部分文件可能未加载。")


        if not all_files_to_load:
            self.status_var.set("拖放的文件/文件夹为空或不符合筛选器。")
            return

        # Remove duplicates that might arise if a file is dropped AND its folder is dropped
        self.populate_original_list(sorted(list(set(all_files_to_load))))


    def load_files(self):
        folder = self.folder_path.get()
        if not folder or not os.path.isdir(folder):
            if folder != "(多个拖放来源)": # Don't show error if it's the DND placeholder
                 messagebox.showerror("错误", "请先选择一个有效的文件夹！")
                 self.status_var.set("错误：文件夹路径无效。")
            else:
                 self.status_var.set("请选择文件夹或拖放文件。") # Or "拖放源已更改, 请重新拖放"
            return

        self.root_folder_for_relative_path = folder # Set for browse mode
        self.clear_lists()

        is_recursive = self.recursive_var.get()
        file_filter = self.filter_var.get().lower()
        files_found = []

        try:
            if is_recursive:
                for root, dirs, files in os.walk(folder):
                    # dirs[:] = [d for d in dirs if not d.startswith('.')] # Example: skip hidden dirs
                    for filename in files:
                        # if filename.startswith('.'): continue # Example: skip hidden files
                        if not file_filter or file_filter in filename.lower():
                             full_path = os.path.join(root, filename)
                             files_found.append(full_path)
            else:
                for filename in os.listdir(folder):
                    full_path = os.path.join(folder, filename)
                    if os.path.isfile(full_path): # Make sure it's a file
                        # if filename.startswith('.'): continue
                        if not file_filter or file_filter in filename.lower():
                            files_found.append(full_path)

            if not files_found:
                self.status_var.set("文件夹为空或无文件匹配筛选器。")
                self.text_original.config(state=tk.NORMAL)
                self.text_original.delete('1.0', tk.END)
                self.text_original.config(state=tk.DISABLED)
                return

            self.populate_original_list(sorted(files_found))

        except Exception as e:
            messagebox.showerror("加载错误", f"加载文件时出错：\n{e}")
            self.status_var.set(f"错误：加载文件失败。")
            self.clear_lists()

    def populate_original_list(self, full_paths):
        self.original_files_full_path = full_paths
        self.original_files_display = []
        for fp in full_paths:
            # For display, we only want the basename.
            # If root_folder_for_relative_path is set, we could show relative paths
            # but for simplicity and consistency, basename is usually fine.
            self.original_files_display.append(os.path.basename(fp))

        self.text_original.config(state=tk.NORMAL)
        self.text_original.delete('1.0', tk.END)
        for idx, display_name in enumerate(self.original_files_display):
            tag = "odd_row" if idx % 2 == 0 else "even_row"
            self.text_original.insert(tk.END, display_name + "\n", (tag,))
        self.text_original.config(state=tk.DISABLED)

        count = len(self.original_files_full_path)
        self.status_var.set(f"成功加载 {count} 个文件。准备复制或生成新名称。")
        self._update_date_format_preview() # Update preview if date format exists

    def copy_original_names(self):
        if not self.original_files_display:
             messagebox.showwarning("提示", "请先加载文件。")
             self.status_var.set("提示：无文件可复制。")
             return
        original_names_text = "\n".join(self.original_files_display)
        if not original_names_text: # Should not happen if original_files_display is populated
             messagebox.showwarning("提示", "左侧列表为空。")
             self.status_var.set("提示：无文件名可复制。")
             return
        try:
            self.master.clipboard_clear()
            self.master.clipboard_append(original_names_text)
            self.status_var.set(f"已复制 {len(self.original_files_display)} 个原始文件名到剪贴板。")
        except tk.TclError:
             messagebox.showerror("错误", "无法访问剪贴板。")
             self.status_var.set("错误：无法复制到剪贴板。")

    def paste_to_new_names(self):
        try:
            clipboard_content = self.master.clipboard_get()
            self.text_new.delete('1.0', tk.END)
            self.text_new.insert('1.0', clipboard_content)
            # Count lines roughly for status
            lines = len([line for line in clipboard_content.splitlines() if line.strip()])
            self.status_var.set(f"已从剪贴板粘贴 {lines} 行到新文件名列表。")
        except tk.TclError: # Clipboard empty or not accessible
            messagebox.showwarning("粘贴错误", "剪贴板为空或无法访问。")
            self.status_var.set("无法从剪贴板粘贴。")
        except Exception as e: # Other potential errors
            messagebox.showerror("粘贴错误", f"粘贴时发生错误:\n{e}")
            self.status_var.set("粘贴时出错。")

    def _check_and_copy_originals_if_new_empty(self):
        """If new names list is empty, copies original basenames to it. Returns False if originals are also empty."""
        if not self.text_new.get('1.0', tk.END).strip(): # If right text area is empty
            if not self.original_files_display:
                messagebox.showinfo("提示", "请先加载原始文件列表。")
                self.status_var.set("提示: 请先加载文件。")
                return False
            # Copy original basenames to the new names list
            self.update_new_names_widget(list(self.original_files_display)) # Use a copy
            self.status_var.set("新列表为空，已从左侧复制文件名。")
            return True
        return True # New list already has content

    def get_new_names_from_widget(self):
        new_names_text = self.text_new.get('1.0', tk.END).strip()
        # Split by newline and filter out empty lines that might result from trailing newlines
        new_names = [name for name in new_names_text.splitlines() if name] # Filter empty lines
        return new_names

    def update_new_names_widget(self, new_names_list):
        self.text_new.delete('1.0', tk.END)
        if new_names_list:
             # Join with newline, add a trailing newline if items exist for consistent display
             display_text = "\n".join(new_names_list) + ("\n" if new_names_list else "")
             self.text_new.insert('1.0', display_text)

    def apply_replace(self):
        if not self._check_and_copy_originals_if_new_empty(): return

        find_text = self.replace_find_var.get()
        replace_text = self.replace_with_var.get()
        case_sensitive = self.replace_case_var.get()
        current_names = self.get_new_names_from_widget()

        if not current_names and not find_text: # Nothing to do if list and find text are empty
             self.status_var.set("列表和查找文本均为空，无操作。")
             return

        modified_names = []
        count = 0 # Count how many names were actually changed

        if case_sensitive:
            for name in current_names:
                new_name = name.replace(find_text, replace_text)
                if name != new_name: count += 1
                modified_names.append(new_name)
        else: # Case-insensitive using regex
            try:
                if not find_text: # If find_text is empty, re.compile will error, so just copy
                    modified_names = list(current_names) # No change if find_text is empty
                else:
                    regex = re.compile(re.escape(find_text), re.IGNORECASE)
                    for name in current_names:
                        new_name, num_subs = regex.subn(replace_text, name)
                        if num_subs > 0: count += 1
                        modified_names.append(new_name)
            except re.error as e:
                 messagebox.showerror("错误", f"正则表达式错误: {e}"); return

        self.update_new_names_widget(modified_names)
        self.status_var.set(f"替换完成，修改了 {count} 项。")

    def apply_insert(self, is_sequence=False, seq_params=None):
        # If not a sequence operation, check and copy originals if new list is empty
        if not is_sequence:
            if not self._check_and_copy_originals_if_new_empty(): return

        text_to_insert_base = self.insert_text_var.get() if not is_sequence else ""
        position_mode = self.seq_pos_var.get() if is_sequence else self.insert_pos_var.get()
        index_str = (self.seq_index_var.get() if is_sequence else self.insert_index_var.get()).strip()

        try:
            index_val = int(index_str) if position_mode == "索引(从0开始)" else 0 # Default index if not used
        except ValueError:
            messagebox.showerror("错误", "索引必须是一个整数."); return

        current_names = self.get_new_names_from_widget()
        if not current_names: # No names to modify
            self.status_var.set("列表为空，无法执行插入/序号操作。")
            return

        modified_names = []
        current_seq_val = seq_params['start'] if is_sequence and seq_params else 0 # Start sequence value

        for i, name in enumerate(current_names):
            final_text_to_insert = text_to_insert_base
            if is_sequence and seq_params:
                seq_num_str = str(current_seq_val)
                if seq_params['pad'] > 0:
                    seq_num_str = seq_num_str.zfill(seq_params['pad'])
                final_text_to_insert = f"{seq_params['prefix']}{seq_num_str}{seq_params['suffix']}"
                current_seq_val += 1 # Increment for next iteration

            if position_mode == "开头":
                modified_names.append(final_text_to_insert + name)
            elif position_mode == "结尾":
                modified_names.append(name + final_text_to_insert)
            elif position_mode == "索引(从0开始)":
                # Clamp index to be within the bounds of the string length
                actual_index = max(0, min(index_val, len(name)))
                modified_names.append(name[:actual_index] + final_text_to_insert + name[actual_index:])
            else: # Should not happen with combobox
                modified_names.append(name)

        self.update_new_names_widget(modified_names)
        rule_type = "序号" if is_sequence else "文本"
        self.status_var.set(f"应用 {rule_type} 插入 完成。")

    def apply_sequence(self):
        if not self._check_and_copy_originals_if_new_empty(): return
        try:
            start = int(self.seq_start_var.get())
            pad = int(self.seq_pad_var.get())
            if pad < 0: pad = 0 # Padding cannot be negative
        except ValueError:
            messagebox.showerror("错误", "序号起始值和补零宽度必须是整数."); return

        seq_params = {
            'start': start,
            'pad': pad,
            'prefix': self.seq_prefix_var.get(),
            'suffix': self.seq_suffix_var.get()
        }
        self.apply_insert(is_sequence=True, seq_params=seq_params)


    def _update_date_format_preview(self, event=None):
        format_string = self.date_format_var.get()
        try:
            now = datetime.now()
            preview_text = now.strftime(format_string)
            self.date_format_preview_label.config(text=f"预览: {preview_text}", foreground="grey")
        except ValueError: # Invalid format string
            self.date_format_preview_label.config(text="格式无效", foreground="red")
        except Exception: # Other errors, e.g., if format_string is too complex or OS specific issues
            self.date_format_preview_label.config(text="错误", foreground="red")

    def apply_creation_date(self):
        if not self.original_files_full_path:
            messagebox.showerror("错误", "请先加载原始文件列表。")
            self.status_var.set("错误: 请先加载文件以获取创建日期。")
            return

        format_string = self.date_format_var.get()
        prefix = self.date_prefix_var.get()
        suffix = self.date_suffix_var.get()

        if not format_string:
            messagebox.showerror("错误", "请输入日期格式字符串 (例如 %Y%m%d)。"); return

        date_based_names = []
        errors = [] # Collect errors during processing

        # Define invalid chars for filenames (OS-dependent)
        # For simplicity, this covers common invalid chars for Windows.
        # More robust checking might be needed for cross-platform strictness.
        invalid_chars_basic = r'<>:"/\|?*' # Common for Windows
        if sys.platform != 'win32': # On POSIX, only / and NUL are strictly forbidden
            invalid_chars_basic = '/'
        # Additionally, we will check for path separators in the generated name part.

        for i, filepath in enumerate(self.original_files_full_path):
            original_basename = os.path.basename(filepath)
            _, ext = os.path.splitext(original_basename) # Preserve original extension

            try:
                timestamp = os.path.getctime(filepath) # Creation time on Windows, last metadata change on Unix
                # Consider os.path.getmtime(filepath) for modification time if preferred
                dt_object = datetime.fromtimestamp(timestamp)
                formatted_date = dt_object.strftime(format_string)

                new_name_part = f"{prefix}{formatted_date}{suffix}"

                # Check for invalid characters in the generated name part (excluding extension)
                if any(char in new_name_part for char in invalid_chars_basic + '/\\') or '\0' in new_name_part:
                     errors.append(f"第 {i+1} 项 '{original_basename}': 生成的日期名称部分 '{new_name_part}' 包含无效字符或路径分隔符。")
                     date_based_names.append(f"<<生成错误: 无效字符>>{ext}"); continue # Append extension to error placeholder

                new_name = f"{new_name_part}{ext}"
                date_based_names.append(new_name)

            except FileNotFoundError:
                errors.append(f"第 {i+1} 项: 原始文件 '{original_basename}' 未找到。")
                date_based_names.append(f"<<文件未找到>>")
            except ValueError as e: # strftime format error
                errors.append(f"日期格式错误: {e} (文件 {i+1})")
                messagebox.showerror("日期格式错误", f"您输入的日期格式 '{format_string}' 无效:\n{e}")
                return # Stop processing if format is bad
            except OSError as e: # Permission errors, etc.
                errors.append(f"第 {i+1} 项 '{original_basename}': 无法访问文件 ({e})")
                date_based_names.append(f"<<访问错误>>{ext}")
            except Exception as e: # Catch-all for other unexpected errors
                errors.append(f"第 {i+1} 项 '{original_basename}': 未知错误 ({e})")
                date_based_names.append(f"<<未知错误>>{ext}")

        self.update_new_names_widget(date_based_names)

        if errors:
            error_details = "\n".join(errors);
            if len(error_details) > 500: error_details = error_details[:500] + "\n..." # Truncate long error lists
            messagebox.showwarning("日期重命名警告", f"已生成日期文件名，但有以下问题:\n\n{error_details}")
            self.status_var.set("根据日期生成名称完成，但有错误。")
        else:
            self.status_var.set(f"已根据文件创建日期生成 {len(date_based_names)} 个新文件名。")

    def preview_and_rename(self):
        if not self.original_files_full_path:
            messagebox.showerror("错误", "没有加载原始文件列表，无法预览。")
            self.status_var.set("错误: 无原始文件。")
            return

        new_names_from_widget = self.get_new_names_from_widget() # Get names from right text area
        original_count = len(self.original_files_full_path)
        new_count = len(new_names_from_widget)

        if original_count == 0:
            messagebox.showinfo("无操作", "没有要重命名的文件。")
            self.status_var.set("提示: 列表为空。")
            return

        if original_count != new_count:
            messagebox.showerror("行数不匹配",
                                 f"原始文件列表有 {original_count} 项，新文件名列表有 {new_count} 项。\n"
                                 "两者数量必须一致才能进行重命名。")
            self.status_var.set("错误: 原始/新文件名数量不匹配。")
            return

        preview_data = []         # For display in preview window
        potential_errors = []     # List of validation errors
        temp_new_paths_check = set() # For checking intra-batch new name collisions (case-insensitive for Windows)

        # Define invalid chars for filenames (OS-dependent)
        invalid_chars_os = r'<>:"/\|?*' if sys.platform == 'win32' else '/'
        # Combine with path separators for a more thorough check against user input mistake
        all_invalid_chars_for_basename = invalid_chars_os + '/\\' # Disallow path separators in new basenames

        for i, old_full_path in enumerate(self.original_files_full_path):
            old_display_name = self.original_files_display[i] # Basename from original list
            new_name_raw_from_widget = new_names_from_widget[i].strip() # Get corresponding new name

            # --- Basic Validation for the new name from widget ---
            if not new_name_raw_from_widget:
                potential_errors.append(f"!! 第 {i+1} 项: 新名称为空 (原始: '{old_display_name}')")
                preview_data.append(f"{old_display_name}{PREVIEW_SEPARATOR}<<错误: 新名称为空>>")
                continue

            if "<<错误" in new_name_raw_from_widget or \
               "<<文件未找到>>" in new_name_raw_from_widget or \
               "<<访问错误>>" in new_name_raw_from_widget or \
               "<<未知错误>>" in new_name_raw_from_widget:
                potential_errors.append(f"!! 第 {i+1} 项: 新名称 '{new_name_raw_from_widget}' 指示先前错误 (原始: '{old_display_name}')")
                preview_data.append(f"{old_display_name}{PREVIEW_SEPARATOR}{new_name_raw_from_widget}") # Show the error placeholder
                continue

            # Check for invalid characters or path separators in the new basename
            if any(char in new_name_raw_from_widget for char in all_invalid_chars_for_basename) or '\0' in new_name_raw_from_widget:
                potential_errors.append(f"!! 第 {i+1} 项: 新名称 '{new_name_raw_from_widget}' 包含无效字符或路径分隔符 (原始: '{old_display_name}')")
                preview_data.append(f"{old_display_name}{PREVIEW_SEPARATOR}<<错误: 无效字符/路径>>")
                continue

            current_file_dir = os.path.dirname(old_full_path)
            new_full_path_candidate = os.path.join(current_file_dir, new_name_raw_from_widget)

            # --- Collision Checks ---
            # 1. Target exists and is NOT the original file (case-sensitive check first)
            target_exists = os.path.exists(new_full_path_candidate)
            is_same_file = False
            if target_exists:
                try:
                    is_same_file = os.path.samefile(old_full_path, new_full_path_candidate)
                except OSError: # samefile can fail if one doesn't exist, but we checked old_full_path and new_full_path_candidate existence
                    is_same_file = (old_full_path.lower() == new_full_path_candidate.lower()) if sys.platform == 'win32' else (old_full_path == new_full_path_candidate)


            if target_exists and not is_same_file:
                potential_errors.append(f"!! 第 {i+1} 项: 目标文件 '{new_name_raw_from_widget}' 已存在于 '{os.path.basename(current_file_dir)}' 且不是原文件。")
                preview_data.append(f"{old_display_name}{PREVIEW_SEPARATOR}<<错误: 目标已存在>>")
                continue

            # 2. Intra-batch collision: check if this new_full_path_candidate (case-insensitively on Win)
            #    has already been used as a target in this renaming batch.
            check_key_path = new_full_path_candidate.lower() if sys.platform == 'win32' else new_full_path_candidate
            if check_key_path in temp_new_paths_check:
                potential_errors.append(f"!! 第 {i+1} 项: 新名称 '{new_name_raw_from_widget}' 在 '{os.path.basename(current_file_dir)}' 中与本批次的其他新名称冲突。")
                preview_data.append(f"{old_display_name}{PREVIEW_SEPARATOR}<<错误: 新名称冲突>>")
                continue
            else:
                # Add only if it's different from original, or if case changes (as os.rename handles case changes)
                # This logic ensures that if A.txt -> a.txt, it's not flagged as a collision with itself if a.txt is already processed.
                # However, the primary check for intra-batch is the `check_key_path`.
                # We add it to the set regardless of whether it's a case-only rename or a full rename.
                temp_new_paths_check.add(check_key_path)


            # If all checks pass for this item
            preview_data.append(f"{old_display_name}{PREVIEW_SEPARATOR}{new_name_raw_from_widget}")

        # --- Show Preview Window ---
        preview_win = tk.Toplevel(self.master)
        preview_win.title("重命名预览 - 请确认")
        try: preview_win.geometry("700x550") # Slightly taller for errors
        except tk.TclError: pass
        preview_win.transient(self.master)
        preview_win.grab_set() # Modal behavior

        preview_label = ttk.Label(preview_win, text=f"将对 {original_count} 个文件执行以下重命名操作 (如果可能):", padding="10")
        preview_label.pack(fill=tk.X)

        preview_text_widget = scrolledtext.ScrolledText(preview_win, wrap=tk.NONE, width=80, height=15) # Reduced height
        preview_text_widget.pack(fill=tk.BOTH, expand=True, padx=10, pady=(0, 5))
        preview_text_widget.insert('1.0', "\n".join(preview_data))
        preview_text_widget.config(state=tk.DISABLED) # Make it read-only

        if potential_errors:
             error_label = ttk.Label(preview_win, text="检测到以下潜在问题 (标记为 <<错误>>，将不会执行):", foreground="red", padding=(10, 5, 10, 5))
             error_label.pack(fill=tk.X)
             error_text_widget = scrolledtext.ScrolledText(preview_win, wrap=tk.NONE, height=7, background="#ffe0e0") # Light red background
             error_text_widget.pack(fill=tk.X, expand=False, padx=10, pady=(0, 10))
             error_text_widget.insert('1.0', "\n".join(potential_errors))
             error_text_widget.config(state=tk.DISABLED) # Read-only

        button_frame = ttk.Frame(preview_win, padding="10")
        button_frame.pack(fill=tk.X)

        confirm_button = ttk.Button(button_frame, text="确认重命名", command=lambda: self.execute_rename(preview_win, new_names_from_widget, preview_data))
        confirm_button.pack(side=tk.RIGHT, padx=5)

        # Disable confirm button if any fatal errors were found in preview_data
        if any("<<错误" in item for item in preview_data):
            confirm_button.config(state=tk.DISABLED)
            ttk.Label(button_frame, text="检测到错误, 无法执行。", foreground="red").pack(side=tk.LEFT, padx=5)

        cancel_button = ttk.Button(button_frame, text="取消", command=preview_win.destroy)
        cancel_button.pack(side=tk.RIGHT, padx=5)

        preview_win.wait_window() # Wait for preview window to close


    def execute_rename(self, preview_window, new_names_list_from_widget, preview_data_for_check):
        preview_window.destroy() # Close the preview window

        renamed_count = 0
        skipped_count = 0 # For files that were already correct or had non-fatal issues handled by preview
        error_count = 0
        errors_during_rename = [] # Store errors that occur during the actual os.rename

        self.status_var.set(f"正在重命名 {len(self.original_files_full_path)} 个文件..."); self.master.update_idletasks()

        # Define invalid chars again, just in case something slipped through or for strictness
        invalid_chars_os_final = r'<>:"/\|?*' if sys.platform == 'win32' else '/'
        all_invalid_chars_final = invalid_chars_os_final + '/\\'

        for i, old_full_path in enumerate(self.original_files_full_path):
            if i >= len(new_names_list_from_widget) or i >= len(preview_data_for_check):
                errors_during_rename.append(f"内部错误: 索引 {i} 超出列表范围。跳过。")
                error_count += 1
                continue

            new_name_raw = new_names_list_from_widget[i].strip()
            old_basename = self.original_files_display[i] # os.path.basename(old_full_path)
            preview_line_for_this_file = preview_data_for_check[i]

            # --- Final Pre-flight Checks based on Preview ---
            # If the preview already marked this item as an error, skip it.
            if "<<错误" in preview_line_for_this_file:
                skipped_count += 1
                # We could log this skip, but potential_errors in preview already covers it
                errors_during_rename.append(f"跳过 '{old_basename}': 预览时标记为错误 ({preview_line_for_this_file.split(PREVIEW_SEPARATOR,1)[1]}).")
                continue

            # Double-check new name for sanity (should have been caught by preview)
            if not new_name_raw:
                skipped_count +=1; continue # Should not happen if preview worked

            if any(char in new_name_raw for char in all_invalid_chars_final) or '\0' in new_name_raw:
                 error_count += 1
                 errors_during_rename.append(f"执行失败 '{old_basename}' -> '{new_name_raw}': 新名称含无效字符或路径分隔符。")
                 continue

            current_file_dir = os.path.dirname(old_full_path)
            new_full_path = os.path.join(current_file_dir, new_name_raw)

            # Skip if old and new full paths are identical (no change needed)
            # os.rename handles case-only changes correctly on Windows (A.txt -> a.txt)
            # On Linux, A.txt and a.txt are different files, so it's a rename.
            if old_full_path == new_full_path:
                 skipped_count += 1
                 continue
            # If only case differs, os.rename will handle it. If basenames are identical, skip.
            if old_basename == new_name_raw and old_full_path.lower() == new_full_path.lower(): # Stricter skip for true no-ops
                 skipped_count += 1
                 continue


            try:
                if not os.path.exists(old_full_path): # File might have been moved/deleted since loading
                    raise FileNotFoundError(f"原始文件 '{old_basename}' 在重命名时未找到。")

                # The preview should have caught existing targets that are not the original file.
                # However, a final check for safety, though it adds a bit of overhead.
                if os.path.exists(new_full_path) and not os.path.samefile(old_full_path, new_full_path):
                     raise FileExistsError(f"目标文件 '{new_name_raw}' 在尝试重命名 '{old_basename}' 时已存在且不是原文件。")

                os.rename(old_full_path, new_full_path)
                renamed_count += 1
                # Update the internal list of full paths for subsequent operations if any
                self.original_files_full_path[i] = new_full_path
                # Also update the display name if it was based on this
                self.original_files_display[i] = new_name_raw

            except OSError as e:
                error_count += 1
                err_msg = f"执行失败 '{old_basename}' -> '{new_name_raw}': OS错误 - {type(e).__name__}: {getattr(e, 'strerror', str(e))}"
                if isinstance(e, FileNotFoundError): err_msg = f"执行失败 '{old_basename}': 原始文件未找到 ({getattr(e, 'strerror', str(e))})"
                elif isinstance(e, FileExistsError): err_msg = f"执行失败 '{old_basename}' -> '{new_name_raw}': 目标已存在 ({getattr(e, 'strerror', str(e))})"
                elif isinstance(e, PermissionError): err_msg = f"执行失败 '{old_basename}' -> '{new_name_raw}': 权限不足 ({getattr(e, 'strerror', str(e))})"
                elif sys.platform == 'win32' and hasattr(e, 'winerror') and e.winerror == 123: # ERROR_INVALID_NAME
                     err_msg = f"执行失败 '{old_basename}' -> '{new_name_raw}': 文件名、目录名或卷标语法不正确。"
                errors_during_rename.append(err_msg)
            except Exception as e: # Catch any other unexpected error
                error_count += 1
                errors_during_rename.append(f"执行失败 '{old_basename}' -> '{new_name_raw}': 意外错误 - {type(e).__name__}: {e}")

        result_message = f"重命名完成: {renamed_count} 个成功, {skipped_count} 个跳过, {error_count} 个失败。"
        self.status_var.set(result_message)

        if errors_during_rename: # Show detailed errors if any occurred during the actual rename phase
            error_details_str = "\n".join(errors_during_rename)
            if len(error_details_str) > 1500: error_details_str = error_details_str[:1500] + "\n..." # Truncate
            messagebox.showerror("重命名操作错误详情", f"{result_message}\n\n在执行过程中发生以下错误:\n{error_details_str}")
        elif renamed_count > 0 or skipped_count > 0 :
            messagebox.showinfo("重命名完成", result_message)
        else: # No renames, no skips (implies all might have been errors caught by preview)
            messagebox.showinfo("无操作", "没有文件被重命名 (可能所有项都在预览时被标记为错误或无需更改)。")

        # After renaming, reload files if a folder was selected, or clear if DND was used
        current_folder_path = self.folder_path.get()
        if current_folder_path and current_folder_path != "(多个拖放来源)" and os.path.isdir(current_folder_path):
            self.load_files() # Reload to reflect changes
        elif current_folder_path == "(多个拖放来源)":
            self.clear_lists() # Clear lists as the source was DND and paths are now changed
            self.status_var.set(f"{result_message} (列表已清除, 请重新拖放文件)")
        else: # Path might be invalid now, clear lists
            self.clear_lists()
            self.status_var.set(f"{result_message} (列表已清除)")


    def clear_lists(self):
        self.clear_original_list()
        self.text_new.delete('1.0', tk.END)

    def clear_original_list(self):
         self.text_original.config(state=tk.NORMAL)
         self.text_original.delete('1.0', tk.END)
         self.text_original.config(state=tk.DISABLED)
         self.original_files_full_path = []
         self.original_files_display = []
         self.status_var.set("列表已清空。")

# --- Main Execution ---
if __name__ == "__main__":
    # Use TkinterDnD.Tk() if DND is available and enabled, otherwise regular tk.Tk()
    root = TkinterDnD.Tk() if USE_DND else tk.Tk()

    if not USE_DND and not getattr(sys, 'frozen', False): # Show warning only if not frozen and DND failed to load
        # This message might be better placed inside the app window if DND fails at runtime
        # but for initial setup, a print or a temporary label is okay.
        # A more integrated approach would be a status bar message or a disabled DND indicator.
        print("WARNING: tkinterdnd2 library not loaded. Drag and drop will not be available.")
        # Optionally, add a label to the root window if it's a persistent issue:
        # ttk.Label(root, text="警告: tkinterdnd2 未加载，拖放功能不可用。",
        #           foreground="orange", padding=5).pack(side=tk.BOTTOM, fill=tk.X)


    # --- Style setup ---
    style = ttk.Style()
    available_themes = style.theme_names()
    # Prefer modern themes if available
    if 'clam' in available_themes: style.theme_use('clam')
    elif 'vista' in available_themes and sys.platform == 'win32': style.theme_use('vista')
    elif 'aqua' in available_themes and sys.platform == 'darwin': style.theme_use('aqua')
    # else, it will use the default theme for the OS

    app = FileRenamerApp(root)
    root.mainloop()
