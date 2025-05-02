import tkinter as tk
from tkinter import ttk, filedialog, messagebox, scrolledtext, font as tkfont
import os
import sys
import re
import time
from datetime import datetime

# --- Try importing tkinterdnd2 ---
try:
    from tkinterdnd2 import DND_FILES, TkinterDnD
    USE_DND = True
except ImportError:
    USE_DND = False
    print("提示: 未找到 'tkinterdnd2' 库。拖放功能将不可用。")
    print("请尝试安装: pip install tkinterdnd2-universal")
    TkinterDnD = tk

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
            self.bold_font = tkfont.Font(font=self.default_font)
            self.bold_font.config(weight='bold')
        self.normal_font = self.default_font

        # --- UI Setup ---
        # Top Frame
        top_frame = ttk.Frame(master, padding="10")
        top_frame.pack(fill=tk.X)
        # (Folder, Recursive, Filter, Load - same as before)
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
        right_pane.grid_rowconfigure(0, weight=1)
        right_controls = ttk.Frame(right_pane)
        right_controls.pack(fill=tk.X, pady=(0, 5))
        ttk.Label(right_controls, text="新文件名 (粘贴或使用下方规则生成/修改)").pack(side=tk.LEFT)
        # --- Add Paste button BEFORE Clear button ---
        self.clear_button_right = ttk.Button(right_controls, text="清除", command=lambda: self.text_new.delete('1.0', tk.END), width=5)
        self.clear_button_right.pack(side=tk.RIGHT, padx=2)
        self.paste_button_right = ttk.Button(right_controls, text="粘贴", command=self.paste_to_new_names, width=5)
        self.paste_button_right.pack(side=tk.RIGHT, padx=2) # Pack paste first (appears before clear)
        # --------------------------------------------
        self.text_new = scrolledtext.ScrolledText(right_pane, wrap=tk.NONE, width=45, height=20)
        self.text_new.pack(fill=tk.BOTH, expand=True)

        # Rules Frame (Below Paned Window)
        rules_frame = ttk.LabelFrame(master, text="快速修改新文件名列表", padding="10")
        rules_frame.pack(fill=tk.X, padx=10, pady=(5, 5))
        rules_frame.grid_columnconfigure(1, weight=1)
        rules_frame.grid_columnconfigure(4, weight=1)
        # (Rules layout remains the same as v1.3)
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
        seq_frame.grid(row=4, column=0, columnspan=3, sticky=tk.EW, padx=5)
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
        seq_pos_frame.grid(row=5, column=1, columnspan=2, padx=5, pady=0, sticky=tk.EW)
        self.seq_pos_var = tk.StringVar(value="开头")
        ttk.Combobox(seq_pos_frame, textvariable=self.seq_pos_var, values=pos_options, state="readonly", width=12).pack(side=tk.LEFT)
        self.seq_index_var = tk.StringVar(value="0")
        ttk.Entry(seq_pos_frame, textvariable=self.seq_index_var, width=4).pack(side=tk.LEFT, padx=(5, 0))
        ttk.Button(rules_frame, text="应用序号", command=self.apply_sequence).grid(row=4, column=3, rowspan=2, padx=(20,5), pady=3, sticky=tk.W + tk.S)
        # -- Creation Date Rule --
        ttk.Label(rules_frame, text="创建日期:", font=self.bold_font).grid(row=3, column=4, padx=5, pady=3, sticky=tk.W)
        date_frame = ttk.Frame(rules_frame)
        date_frame.grid(row=4, column=4, columnspan=2, sticky=tk.EW, padx=5)
        ttk.Label(date_frame, text="格式:").pack(side=tk.LEFT, padx=(0,2))
        self.date_format_var = tk.StringVar(value=DEFAULT_DATE_FORMAT)
        self.date_format_entry = ttk.Entry(date_frame, textvariable=self.date_format_var, width=18)
        self.date_format_entry.pack(side=tk.LEFT, padx=(0,10))
        self.date_format_entry.bind("<KeyRelease>", self._update_date_format_preview)
        self.date_format_preview_label = ttk.Label(date_frame, text="", foreground="grey")
        self.date_format_preview_label.pack(side=tk.LEFT)
        self._update_date_format_preview()
        ttk.Label(rules_frame, text="前缀:").grid(row=5, column=4, padx=5, pady=3, sticky=tk.W)
        self.date_prefix_var = tk.StringVar(value="")
        ttk.Entry(rules_frame, textvariable=self.date_prefix_var, width=10).grid(row=5, column=4, padx=(45,5), pady=3, sticky=tk.W)
        ttk.Label(rules_frame, text="后缀:").grid(row=5, column=4, padx=(140,5), pady=3, sticky=tk.W)
        self.date_suffix_var = tk.StringVar(value="")
        ttk.Entry(rules_frame, textvariable=self.date_suffix_var, width=10).grid(row=5, column=4, padx=(180,5), pady=3, sticky=tk.W)
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

    # --- File Loading and Handling Methods (browse_folder, trigger_reload, handle_drop, load_files, populate_original_list, copy_original_names) ---
    # These remain the same as v1.3 - populate_original_list correctly displays only basenames
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
        cleaned_data = raw_data.strip('{} ')
        potential_paths = []
        if '\n' in cleaned_data:
            potential_paths = [p.strip() for p in cleaned_data.split('\n') if p.strip()]
        else:
            potential_paths = re.findall(r'\{[^{}]*\}|\"[^"]*\"|\S+', raw_data)
            potential_paths = [p.strip('{} "') for p in potential_paths if p.strip()]

        dropped_files = []
        dropped_folders = []
        for path_str in potential_paths:
             if not path_str: continue
             path_str = path_str.strip('"')
             if os.path.isfile(path_str):
                 dropped_files.append(os.path.abspath(path_str))
             elif os.path.isdir(path_str):
                 dropped_folders.append(os.path.abspath(path_str))
             else:
                  print(f"Skipping invalid dropped item: {path_str}")

        if not dropped_files and not dropped_folders:
            self.status_var.set("拖放未包含有效的文件或文件夹。")
            return

        all_paths_for_common = [os.path.dirname(f) for f in dropped_files] + dropped_folders
        if all_paths_for_common:
            try:
                self.root_folder_for_relative_path = os.path.commonpath(all_paths_for_common)
            except ValueError:
                self.root_folder_for_relative_path = None
        else:
            self.root_folder_for_relative_path = None

        self.clear_lists()
        self.folder_path.set("(多个拖放来源)")

        all_files_to_load = list(dropped_files)
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
                else:
                    for filename in os.listdir(current_root_for_walk):
                        full_path = os.path.join(current_root_for_walk, filename)
                        if os.path.isfile(full_path):
                            if not file_filter or file_filter in filename.lower():
                                all_files_to_load.append(full_path)
            except Exception as e:
                 print(f"Error reading dropped folder {folder}: {e}")
                 self.status_var.set(f"读取文件夹 {os.path.basename(folder)} 时出错, 部分文件可能未加载。")

        if not all_files_to_load:
            self.status_var.set("拖放的文件/文件夹为空或不符合筛选器。")
            return

        self.populate_original_list(sorted(list(set(all_files_to_load))))

    def load_files(self):
        folder = self.folder_path.get()
        if not folder or not os.path.isdir(folder):
            if folder != "(多个拖放来源)":
                 messagebox.showerror("错误", "请先选择一个有效的文件夹！")
                 self.status_var.set("错误：文件夹路径无效。")
            else:
                 self.status_var.set("请选择文件夹或拖放文件。")
            return

        self.root_folder_for_relative_path = folder
        self.clear_lists()

        is_recursive = self.recursive_var.get()
        file_filter = self.filter_var.get().lower()
        files_found = []

        try:
            if is_recursive:
                for root, dirs, files in os.walk(folder):
                    for filename in files:
                        if not file_filter or file_filter in filename.lower():
                             full_path = os.path.join(root, filename)
                             files_found.append(full_path)
            else:
                for filename in os.listdir(folder):
                    full_path = os.path.join(folder, filename)
                    if os.path.isfile(full_path):
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
            self.original_files_display.append(os.path.basename(fp))

        self.text_original.config(state=tk.NORMAL)
        self.text_original.delete('1.0', tk.END)
        for idx, display_name in enumerate(self.original_files_display):
            tag = "odd_row" if idx % 2 == 0 else "even_row"
            self.text_original.insert(tk.END, display_name + "\n", (tag,))
        self.text_original.config(state=tk.DISABLED)

        count = len(self.original_files_full_path)
        self.status_var.set(f"成功加载 {count} 个文件。准备复制或生成新名称。")
        self._update_date_format_preview()

    def copy_original_names(self):
        if not self.original_files_display:
             messagebox.showwarning("提示", "请先加载文件。")
             self.status_var.set("提示：无文件可复制。")
             return
        original_names_text = "\n".join(self.original_files_display)
        if not original_names_text:
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

    # --- Paste Method ---
    def paste_to_new_names(self):
        """Pastes clipboard content into the right text area, replacing current content."""
        try:
            clipboard_content = self.master.clipboard_get()
            self.text_new.delete('1.0', tk.END)
            self.text_new.insert('1.0', clipboard_content)
            # Count lines roughly for status
            lines = len([line for line in clipboard_content.splitlines() if line.strip()])
            self.status_var.set(f"已从剪贴板粘贴 {lines} 行到新文件名列表。")
        except tk.TclError:
            messagebox.showwarning("粘贴错误", "剪贴板为空或无法访问。")
            self.status_var.set("无法从剪贴板粘贴。")
        except Exception as e:
            messagebox.showerror("粘贴错误", f"粘贴时发生错误:\n{e}")
            self.status_var.set("粘贴时出错。")

    # --- Basic Renaming Rules Methods (_check_and_copy..., get_new_names..., update_new_names..., apply_replace, apply_insert, apply_sequence, _update_date..., apply_creation_date) ---
    # These remain the same as v1.3, including the copy-on-empty logic for relevant rules
    def _check_and_copy_originals_if_new_empty(self):
        if not self.text_new.get('1.0', tk.END).strip():
            if not self.original_files_display:
                messagebox.showinfo("提示", "请先加载原始文件列表。")
                return False
            self.update_new_names_widget(list(self.original_files_display))
            return True
        return True

    def get_new_names_from_widget(self):
        new_names_text = self.text_new.get('1.0', tk.END).strip()
        new_names = [name for name in new_names_text.splitlines() if name]
        return new_names

    def update_new_names_widget(self, new_names_list):
        self.text_new.delete('1.0', tk.END)
        if new_names_list:
             display_text = "\n".join(new_names_list)
             self.text_new.insert('1.0', display_text)

    def apply_replace(self):
        if not self._check_and_copy_originals_if_new_empty(): return
        find_text = self.replace_find_var.get()
        replace_text = self.replace_with_var.get()
        case_sensitive = self.replace_case_var.get()
        current_names = self.get_new_names_from_widget()
        if not current_names and not find_text:
             self.status_var.set("列表和查找文本均为空，无操作。")
             return
        modified_names = []
        count = 0
        if case_sensitive:
            for name in current_names:
                new_name = name.replace(find_text, replace_text)
                if name != new_name: count += 1
                modified_names.append(new_name)
        else:
            try:
                if not find_text: modified_names = list(current_names)
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
        if not is_sequence:
            if not self._check_and_copy_originals_if_new_empty(): return
        text_to_insert_base = self.insert_text_var.get() if not is_sequence else ""
        position_mode = self.seq_pos_var.get() if is_sequence else self.insert_pos_var.get()
        index_str = (self.seq_index_var.get() if is_sequence else self.insert_index_var.get()).strip()
        try: index = int(index_str) if position_mode == "索引(从0开始)" else 0
        except ValueError: messagebox.showerror("错误", "索引必须是一个整数."); return
        current_names = self.get_new_names_from_widget()
        if not current_names:
            self.status_var.set("列表为空，无法执行插入/序号操作。")
            return
        modified_names = []
        current_seq = seq_params['start'] if is_sequence else 0
        for i, name in enumerate(current_names):
            final_text_to_insert = text_to_insert_base
            if is_sequence:
                seq_num_str = str(current_seq)
                if seq_params['pad'] > 0: seq_num_str = seq_num_str.zfill(seq_params['pad'])
                final_text_to_insert = f"{seq_params['prefix']}{seq_num_str}{seq_params['suffix']}"
                current_seq += 1
            if position_mode == "开头": modified_names.append(final_text_to_insert + name)
            elif position_mode == "结尾": modified_names.append(name + final_text_to_insert)
            elif position_mode == "索引(从0开始)":
                if index < 0: index = 0
                if index > len(name): index = len(name)
                modified_names.append(name[:index] + final_text_to_insert + name[index:])
            else: modified_names.append(name)
        self.update_new_names_widget(modified_names)
        rule_type = "序号" if is_sequence else "文本"
        self.status_var.set(f"应用 {rule_type} 插入 完成。")

    def apply_sequence(self):
        if not self._check_and_copy_originals_if_new_empty(): return
        try:
            start = int(self.seq_start_var.get())
            pad = int(self.seq_pad_var.get())
            if pad < 0: pad = 0
        except ValueError: messagebox.showerror("错误", "序号起始值和补零宽度必须是整数."); return
        seq_params = {'start': start, 'pad': pad, 'prefix': self.seq_prefix_var.get(), 'suffix': self.seq_suffix_var.get()}
        self.apply_insert(is_sequence=True, seq_params=seq_params)

    def _update_date_format_preview(self, event=None):
        format_string = self.date_format_var.get()
        try:
            now = datetime.now()
            preview_text = now.strftime(format_string)
            self.date_format_preview_label.config(text=f"预览: {preview_text}", foreground="grey")
        except ValueError: self.date_format_preview_label.config(text="格式无效", foreground="red")
        except Exception: self.date_format_preview_label.config(text="错误", foreground="red")

    def apply_creation_date(self):
        if not self.original_files_full_path: messagebox.showerror("错误", "请先加载原始文件列表。"); return
        format_string = self.date_format_var.get()
        prefix = self.date_prefix_var.get()
        suffix = self.date_suffix_var.get()
        if not format_string: messagebox.showerror("错误", "请输入日期格式字符串."); return
        date_based_names = []
        errors = []
        for i, filepath in enumerate(self.original_files_full_path):
            original_basename = os.path.basename(filepath)
            _, ext = os.path.splitext(original_basename)
            try:
                timestamp = os.path.getctime(filepath)
                dt_object = datetime.fromtimestamp(timestamp)
                formatted_date = dt_object.strftime(format_string)
                new_name = f"{prefix}{formatted_date}{suffix}{ext}"
                invalid_chars = r'<>:"/\|?*' if sys.platform == 'win32' else '/'
                if any(char in new_name for char in invalid_chars + '/\\') or '\0' in new_name: # Added path sep check here too
                     errors.append(f"第 {i+1} 项 '{original_basename}': 生成的日期名称 '{new_name}' 包含无效字符。")
                     date_based_names.append(f"<<生成错误: 无效字符>>"); continue
                date_based_names.append(new_name)
            except FileNotFoundError: errors.append(f"第 {i+1} 项: 原始文件 '{original_basename}' 未找到。"); date_based_names.append(f"<<文件未找到>>")
            except ValueError as e: errors.append(f"日期格式错误: {e} (文件 {i+1})"); messagebox.showerror("日期格式错误", f"格式 '{format_string}' 无效:\n{e}"); return
            except OSError as e: errors.append(f"第 {i+1} 项 '{original_basename}': 无法访问文件 ({e})"); date_based_names.append(f"<<访问错误>>")
            except Exception as e: errors.append(f"第 {i+1} 项 '{original_basename}': 未知错误 ({e})"); date_based_names.append(f"<<未知错误>>")
        self.update_new_names_widget(date_based_names)
        if errors:
            error_details = "\n".join(errors);
            if len(error_details) > 500: error_details = error_details[:500] + "\n..."
            messagebox.showwarning("日期重命名警告", f"已生成日期文件名，但有以下问题:\n\n{error_details}")
            self.status_var.set("根据日期生成名称完成，但有错误。")
        else: self.status_var.set(f"已根据日期生成 {len(date_based_names)} 个新文件名。")


    # --- Renaming Logic ---

    def preview_and_rename(self):
        if not self.original_files_full_path: messagebox.showerror("错误", "没有加载原始文件列表."); return
        new_names = self.get_new_names_from_widget()
        original_count = len(self.original_files_full_path)
        new_count = len(new_names)
        if original_count == 0: messagebox.showinfo("无操作", "没有要重命名的文件."); return
        if original_count != new_count: messagebox.showerror("行数不匹配", f"原始({original_count})与新({new_count})行数不匹配。"); return

        preview_data = []
        potential_errors = []
        temp_new_paths = set()

        # Define invalid chars based on OS
        invalid_chars = r'<>:"/\|?*' if sys.platform == 'win32' else '/'
        # --- FIX: Combine invalid chars and path separators into ONE string ---
        all_invalid_chars = invalid_chars + '/\\'
        # --------------------------------------------------------------------

        for i, old_full_path in enumerate(self.original_files_full_path):
            old_display_name = self.original_files_display[i]
            new_name_raw = new_names[i].strip()

            # --- Validation ---
            if not new_name_raw or "<<错误" in new_name_raw or "<<文件未找到>>" in new_name_raw or "<<访问错误>>" in new_name_raw or "<<未知错误>>" in new_name_raw:
                potential_errors.append(f"!! 第 {i+1} 项: 新名称无效/为空 (原始: '{old_display_name}')")
                preview_data.append(f"{old_display_name}{PREVIEW_SEPARATOR}<<错误: 名称无效/为空>>"); continue

            # --- FIX: Use the combined invalid char string in the check ---
            if any(char in new_name_raw for char in all_invalid_chars) or '\0' in new_name_raw:
            # ------------------------------------------------------------
                potential_errors.append(f"!! 第 {i+1} 项: 新名称 '{new_name_raw}' 含无效字符或路径分隔符")
                preview_data.append(f"{old_display_name}{PREVIEW_SEPARATOR}<<错误: 无效字符/路径>>"); continue

            folder = os.path.dirname(old_full_path)
            new_full_path = os.path.join(folder, new_name_raw)

            is_different_file = True
            try:
                 if os.path.exists(new_full_path) and os.path.samefile(old_full_path, new_full_path): is_different_file = False
                 elif os.path.exists(new_full_path): is_different_file = True
                 else: is_different_file = True
            except OSError: is_different_file = old_full_path.lower() != new_full_path.lower()

            if is_different_file and os.path.exists(new_full_path):
                 potential_errors.append(f"!! 第 {i+1} 项: 目标 '{new_name_raw}' 已存在于 '{os.path.basename(folder)}'")
                 preview_data.append(f"{old_display_name}{PREVIEW_SEPARATOR}<<错误: 目标已存在>>"); continue

            check_path_key = new_full_path.lower() if sys.platform == 'win32' else new_full_path
            if check_path_key in temp_new_paths:
                 potential_errors.append(f"!! 第 {i+1} 项: 新名称 '{new_name_raw}' 在 '{os.path.basename(folder)}' 中与本批次冲突")
                 preview_data.append(f"{old_display_name}{PREVIEW_SEPARATOR}<<错误: 新名称冲突>>"); continue
            else: temp_new_paths.add(check_path_key)

            preview_data.append(f"{old_display_name}{PREVIEW_SEPARATOR}{new_name_raw}")

        # --- Show Preview Window ---
        preview_win = tk.Toplevel(self.master)
        preview_win.title("重命名预览 - 请确认")
        preview_win.geometry("700x500")
        preview_win.transient(self.master)
        preview_win.grab_set()
        preview_label = ttk.Label(preview_win, text=f"将执行以下 {original_count} 个重命名操作：", padding="10"); preview_label.pack(fill=tk.X)
        preview_text = scrolledtext.ScrolledText(preview_win, wrap=tk.NONE, width=80, height=20); preview_text.pack(fill=tk.BOTH, expand=True, padx=10, pady=(0, 10))
        preview_text.insert('1.0', "\n".join(preview_data)); preview_text.config(state=tk.DISABLED)
        if potential_errors:
             error_label = ttk.Label(preview_win, text="检测到潜在问题 (标记为 <<错误>>):", foreground="red", padding=(10, 0, 10, 5)); error_label.pack(fill=tk.X)
             error_text_widget = scrolledtext.ScrolledText(preview_win, wrap=tk.NONE, height=5, background="#ffe0e0"); error_text_widget.pack(fill=tk.X, expand=False, padx=10, pady=(0, 10))
             error_text_widget.insert('1.0', "\n".join(potential_errors)); error_text_widget.config(state=tk.DISABLED)
        button_frame = ttk.Frame(preview_win, padding="10"); button_frame.pack(fill=tk.X)
        confirm_button = ttk.Button(button_frame, text="确认重命名", command=lambda: self.execute_rename(preview_win, new_names)); confirm_button.pack(side=tk.RIGHT, padx=5)
        if any("<<错误" in item for item in preview_data):
            confirm_button.config(state=tk.DISABLED)
            ttk.Label(button_frame, text="检测到错误, 无法执行。", foreground="red").pack(side=tk.LEFT)
        cancel_button = ttk.Button(button_frame, text="取消", command=preview_win.destroy); cancel_button.pack(side=tk.RIGHT, padx=5)
        preview_win.wait_window()

    def execute_rename(self, preview_window, new_names):
        preview_window.destroy()
        renamed_count = 0; skipped_count = 0; error_count = 0; errors = []
        self.status_var.set(f"正在重命名 {len(self.original_files_full_path)} 个文件..."); self.master.update_idletasks()

        # Define invalid chars again for execution check
        invalid_chars = r'<>:"/\|?*' if sys.platform == 'win32' else '/'
        all_invalid_chars = invalid_chars + '/\\'

        for i, old_full_path in enumerate(self.original_files_full_path):
            if i >= len(new_names): errors.append(f"错误: 内部列表索引 ({i}) 超出范围。"); error_count += 1; continue
            new_name_raw = new_names[i].strip()
            old_basename = os.path.basename(old_full_path)

            if not new_name_raw or "<<错误" in new_name_raw or "<<文件未找到>>" in new_name_raw or "<<访问错误>>" in new_name_raw or "<<未知错误>>" in new_name_raw:
                skipped_count += 1; continue
            if any(char in new_name_raw for char in all_invalid_chars) or '\0' in new_name_raw:
                 error_count += 1; errors.append(f"失败 '{old_basename}' -> '{new_name_raw}': 含无效字符/路径。"); continue

            folder = os.path.dirname(old_full_path)
            new_full_path = os.path.join(folder, new_name_raw)

            # Skip if identical (respecting OS case sensitivity implicitly via os.rename)
            if old_full_path == new_full_path or old_basename == new_name_raw:
                 # Allow rename if only case differs? os.rename handles this.
                 # Let's check basename equality specifically to skip if truly identical
                 if old_basename == new_name_raw:
                     skipped_count += 1
                     continue

            try:
                # Minimal check before rename, rely mostly on preview validation
                # if os.path.exists(new_full_path) and not os.path.samefile(old_full_path, new_full_path):
                #      raise FileExistsError(f"Target '{new_name_raw}' exists and is not the original file.")

                os.rename(old_full_path, new_full_path)
                renamed_count += 1
                self.original_files_full_path[i] = new_full_path
            except OSError as e:
                error_count += 1
                # Refined error messages
                if isinstance(e, FileNotFoundError): errors.append(f"失败 '{old_basename}': 原始文件未找到 ({e.strerror})")
                elif isinstance(e, FileExistsError): errors.append(f"失败 '{old_basename}' -> '{new_name_raw}': 目标已存在 ({e.strerror})")
                elif isinstance(e, PermissionError): errors.append(f"失败 '{old_basename}' -> '{new_name_raw}': 权限不足 ({e.strerror})")
                # Handle invalid filename error specifically on Windows if possible
                elif sys.platform == 'win32' and e.winerror == 123: # ERROR_INVALID_NAME
                     errors.append(f"失败 '{old_basename}' -> '{new_name_raw}': 文件名、目录名或卷标语法不正确。")
                else: errors.append(f"失败 '{old_basename}' -> '{new_name_raw}': OS错误 ({type(e).__name__}: {e.strerror})")
            except Exception as e:
                error_count += 1; errors.append(f"失败 '{old_basename}' -> '{new_name_raw}': 意外错误 ({type(e).__name__}: {e})")

        result_message = f"完成: {renamed_count} 成功, {skipped_count} 跳过, {error_count} 失败。"
        self.status_var.set(result_message)
        if errors:
            error_details = "\n".join(errors);
            if len(error_details) > 1500: error_details = error_details[:1500] + "\n..."
            messagebox.showerror("重命名错误详情", f"{result_message}\n\n错误详情:\n{error_details}")
        elif renamed_count > 0 or skipped_count > 0 : messagebox.showinfo("重命名完成", result_message)
        else: messagebox.showinfo("无操作", "没有文件被重命名。")

        folder = self.folder_path.get()
        if folder and folder != "(多个拖放来源)" and os.path.isdir(folder): self.load_files()
        elif folder == "(多个拖放来源)": self.clear_lists(); self.status_var.set(f"{result_message} (列表已清除, 请重新拖放)")

    # --- Utility Functions ---
    def clear_lists(self): self.clear_original_list(); self.text_new.delete('1.0', tk.END)
    def clear_original_list(self):
         self.text_original.config(state=tk.NORMAL); self.text_original.delete('1.0', tk.END); self.text_original.config(state=tk.DISABLED)
         self.original_files_full_path = []; self.original_files_display = []
         self.status_var.set("列表已清空。")

# --- Main Execution ---
if __name__ == "__main__":
    root = TkinterDnD.Tk() if USE_DND else tk.Tk()
    if not USE_DND: ttk.Label(root, text="警告: tkinterdnd2 未加载，拖放功能不可用。", foreground="orange", padding=5).pack(side=tk.BOTTOM, fill=tk.X)
    style = ttk.Style()
    available_themes = style.theme_names()
    if 'clam' in available_themes: style.theme_use('clam')
    elif 'vista' in available_themes and sys.platform == 'win32': style.theme_use('vista')
    elif 'aqua' in available_themes and sys.platform == 'darwin': style.theme_use('aqua')
    app = FileRenamerApp(root)
    root.mainloop()
