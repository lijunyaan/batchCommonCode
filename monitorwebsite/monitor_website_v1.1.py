# -*- coding: utf-8 -*-
import os
import time
import html
import yagmail
import hashlib
import logging
import difflib
import traceback
from dotenv import load_dotenv
from datetime import datetime, timedelta # 用于管理检查时间
from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeoutError, Error as PlaywrightError

# --- Load Environment Variables ---
load_dotenv()

# --- Configuration ---

# 1. Load Mail Configuration from Environment Variables
SMTP_SERVER = os.getenv("SMTP_SERVER")
SMTP_PORT_STR = os.getenv("SMTP_PORT")
EMAIL_ACCOUNT = os.getenv("EMAIL_ACCOUNT")
EMAIL_PASSWORD = os.getenv("EMAIL_PASSWORD")
SENDER_NAME = os.getenv("SENDER_NAME", "网页监控机器人")
ADMIN_EMAIL = os.getenv("ADMIN_EMAIL")

# 2. Load Browser and Logging Configuration from Environment Variables
#    提供合理的默认值以防 .env 文件中未设置
DEFAULT_USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36"
USER_AGENT = os.getenv("USER_AGENT", DEFAULT_USER_AGENT)
LOG_FILE = os.getenv("LOG_FILE", "monitor.log")
LOG_LEVEL_STR = os.getenv("LOG_LEVEL", "INFO").upper()

# 将日志级别字符串转换为 logging 模块的常量
LOG_LEVEL_MAP = {
    'DEBUG': logging.DEBUG,
    'INFO': logging.INFO,
    'WARNING': logging.WARNING,
    'ERROR': logging.ERROR,
    'CRITICAL': logging.CRITICAL
}
LOG_LEVEL = LOG_LEVEL_MAP.get(LOG_LEVEL_STR, logging.INFO) # 默认为 INFO

# --- Validate Essential Mail Configuration ---
if not all([SMTP_SERVER, SMTP_PORT_STR, EMAIL_ACCOUNT, EMAIL_PASSWORD]):
    print("错误：邮件配置不完整。请确保 .env 文件中包含 SMTP_SERVER, SMTP_PORT, EMAIL_ACCOUNT, 和 EMAIL_PASSWORD。")
    exit(1)
try:
    SMTP_PORT = int(SMTP_PORT_STR)
except ValueError:
    print(f"错误：.env 文件中的 SMTP_PORT ('{SMTP_PORT_STR}') 不是有效的数字。")
    exit(1)

# 3. Monitoring Targets (*** 在这里配置监控目标和各自的间隔 ***)
#    现在每个目标包含 'interval_seconds'
MIN_CHECK_INTERVAL = 30 # 设置一个最小的循环检查间隔，避免CPU空转太厉害
MONITOR_TARGETS = [
    {
        "name": "中国水土保持学会动态新闻监控",
        "url": "https://www.sbxh.org.cn/news",     # *** 修改为实际 URL ***
        "selector": "#news-list",           # *** 修改为实际 CSS 选择器 ***
        "recipients": ["369996890@qq.com"], # *** 修改为实际收件人列表 ***
        "state_dir": "monitor_states",      # 状态子目录名
        "interval_seconds": 300,            # <--- 此目标的检查间隔 (秒), 例如 5 分钟
        "wait_for_load_state": "networkidle", # Playwright 等待状态 (可选)
        "wait_timeout": 60000,              # Playwright 等待超时(毫秒)
    },
    # {
    #     "name": "静态公告页面",
    #     "url": "YOUR_STATIC_SITE_URL",
    #     "selector": "div.announcements",
    #     "recipients": ["admin@example.com"],
    #     "state_dir": "monitor_states",
    #     "interval_seconds": 900,            # <--- 此目标的检查间隔 (秒), 例如 15 分钟
    #     "wait_for_load_state": "load",
    #     "wait_timeout": 30000,
    # },
    # --- 在此添加更多监控目标 ---
]

# --- Configuration End ---

# --- Base Directory Setup ---
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
STATE_BASE_DIR = SCRIPT_DIR

# --- Logging Setup (使用从 .env 加载的配置) ---
log_file_path = os.path.join(STATE_BASE_DIR, LOG_FILE)
logging.basicConfig(
    level=LOG_LEVEL, # <--- 使用加载的日志级别
    format='%(asctime)s - %(levelname)s - [%(target_name)s] - %(message)s',
    handlers=[
        logging.FileHandler(log_file_path, encoding='utf-8'), # <--- 使用加载的日志文件名
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)
class TargetLogAdapter(logging.LoggerAdapter):
    def process(self, msg, kwargs):
        if 'target_name' not in self.extra:
            self.extra['target_name'] = 'System'
        return msg, kwargs
log_adapter = TargetLogAdapter(logger, {'target_name': 'System'})

# --- Helper Functions (get_safe_filename, ensure_dir_exists) ---
# (保持不变)
def get_safe_filename(name_or_url):
    sanitized = name_or_url.replace("http://", "").replace("https://", "")
    sanitized = "".join([c if c.isalnum() or c in ('-', '_', '.') else '_' for c in sanitized])
    return sanitized[:100]

def ensure_dir_exists(dir_path):
    if not os.path.exists(dir_path):
        try:
            os.makedirs(dir_path)
            log_adapter.info(f"创建状态目录: {dir_path}", extra={'target_name': 'System'})
        except OSError as e:
            log_adapter.error(f"无法创建状态目录: {dir_path}, 错误: {e}", extra={'target_name': 'System'}, exc_info=True)
            raise

# --- Core Functions ---

def get_target_content_and_hash(url, selector, target_name, wait_for_load_state=None, wait_timeout=60000):
    """使用 Playwright 获取动态加载的内容及其哈希值"""
    adapter_extra = {'target_name': target_name}
    log_adapter.info(f"开始使用 Playwright 获取内容: {url}", extra=adapter_extra)
    content_to_check = None
    current_hash = None
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            # --- 使用从 .env 加载的 USER_AGENT ---
            page = browser.new_page(user_agent=USER_AGENT)
            log_adapter.info(f"导航到: {url}", extra=adapter_extra)
            page.goto(url, timeout=wait_timeout, wait_until=wait_for_load_state or 'load')
            log_adapter.info(f"等待选择器加载: '{selector or '整个页面'}' (最长 {wait_timeout} ms)", extra=adapter_extra)
            if selector:
                try:
                    target_element = page.locator(selector).first
                    target_element.wait_for(state="visible", timeout=wait_timeout)
                    content_to_check = target_element.inner_html()
                    log_adapter.info(f"成功定位并提取选择器 '{selector}' 的内容", extra=adapter_extra)
                except PlaywrightTimeoutError:
                    log_adapter.error(f"等待选择器 '{selector}' 超时 ({wait_timeout} ms)", extra=adapter_extra)
                    browser.close(); return None, None
                except PlaywrightError as e:
                    log_adapter.error(f"定位选择器 '{selector}' 时出错: {e}", extra=adapter_extra)
                    browser.close(); return None, None
            else:
                content_to_check = page.content()
                log_adapter.info("未指定选择器，获取整个渲染后的页面内容", extra=adapter_extra)
            browser.close()
            if content_to_check is not None:
                current_hash = hashlib.sha256(content_to_check.encode('utf-8')).hexdigest()
                log_adapter.info(f"内容获取和哈希计算成功, 哈希: {current_hash[:10]}...", extra=adapter_extra)
            else:
                 log_adapter.warning("未能获取到有效内容", extra=adapter_extra)
    except PlaywrightTimeoutError:
        log_adapter.error(f"Playwright 导航或等待超时: {url}", extra=adapter_extra)
    except PlaywrightError as e:
         log_adapter.error(f"Playwright 操作时发生错误: {url}, 错误: {e}", extra=adapter_extra)
    except Exception as e:
        log_adapter.error(f"获取内容时发生未知错误: {e}", extra=adapter_extra, exc_info=True)
    return content_to_check, current_hash

def read_previous_state(hash_filepath, content_filepath, target_name):
    """读取上次保存的哈希和内容"""
    # (保持不变)
    adapter_extra = {'target_name': target_name}
    previous_hash = None; previous_content = None
    if os.path.exists(hash_filepath):
        try:
            with open(hash_filepath, 'r', encoding='utf-8') as f: previous_hash = f.read().strip()
        except IOError as e: log_adapter.error(f"读取哈希文件失败: {hash_filepath}, 错误: {e}", extra=adapter_extra)
    if os.path.exists(content_filepath):
        try:
            with open(content_filepath, 'r', encoding='utf-8') as f: previous_content = f.read()
        except IOError as e: log_adapter.error(f"读取旧内容文件失败: {content_filepath}, 错误: {e}", extra=adapter_extra)
    if previous_hash: log_adapter.info(f"读取到上次哈希: {previous_hash[:10]}...", extra=adapter_extra)
    else: log_adapter.info("未找到上次状态文件，将首次获取内容作为基准", extra=adapter_extra)
    return previous_hash, previous_content

def write_current_state(hash_filepath, content_filepath, current_hash, current_content, target_name):
    """将当前哈希和内容写入文件"""
    # (保持不变)
    adapter_extra = {'target_name': target_name}
    try:
        with open(hash_filepath, 'w', encoding='utf-8') as f: f.write(current_hash)
        with open(content_filepath, 'w', encoding='utf-8') as f: f.write(str(current_content) if current_content is not None else "")
        log_adapter.info(f"成功将新状态写入文件 ({os.path.basename(hash_filepath)}, {os.path.basename(content_filepath)})", extra=adapter_extra)
    except IOError as e: log_adapter.error(f"写入状态文件失败: {hash_filepath} 或 {content_filepath}, 错误: {e}", extra=adapter_extra)
    except Exception as e: log_adapter.error(f"写入状态时发生未知错误: {e}", extra=adapter_extra, exc_info=True)

def generate_diff_html(old_content, new_content, target_name):
    """使用 difflib 生成 HTML 格式的差异对比"""
    # (保持不变)
    adapter_extra = {'target_name': target_name}
    if old_content is None or new_content is None :
        log_adapter.info("缺少旧内容或新内容，无法生成差异对比。", extra=adapter_extra)
        new_content_escaped = html.escape(str(new_content)) if new_content is not None else "<i>(无法获取当前内容)</i>"
        return f"<p><b>检测到变化（无法生成差异对比）：</b></p><pre>{new_content_escaped}</pre>"
    log_adapter.info("正在生成内容差异...", extra=adapter_extra)
    old_lines = str(old_content).splitlines(); new_lines = str(new_content).splitlines()
    diff = difflib.HtmlDiff(wrapcolumn=80)
    try:
        diff_table = diff.make_file(old_lines, new_lines, fromdesc="旧内容", todesc="新内容", context=True, numlines=5)
        log_adapter.info("内容差异生成完毕。", extra=adapter_extra)
    except Exception as e:
        log_adapter.error(f"生成差异对比时出错: {e}", extra=adapter_extra, exc_info=True)
        new_content_escaped = html.escape(str(new_content))
        return f"<p><b>检测到变化（生成差异对比时出错）：</b></p><p>错误信息：{html.escape(str(e))}</p><p><b>新内容：</b></p><pre>{new_content_escaped}</pre>"
    return f"""
    <p><b>检测到内容变化（差异对比）：</b></p>
    <style> table.diff {{font-family: Courier, monospace; border: solid 1px #ccc; border-collapse: collapse; width: 98%; margin: 10px auto;}} tbody {{font-size: 0.9em;}} .diff_header {{background-color:#f0f0f0; padding: 4px; font-weight: bold;}} td.diff_header {{text-align:right; padding-right: 10px;}} .diff_next {{background-color:#ddd;}} .diff_add {{background-color:#ddffdd;}} .diff_chg {{background-color:#ffffcc;}} .diff_sub {{background-color:#ffdddd;}} td {{padding: 2px 4px; vertical-align: top; white-space: pre-wrap; word-wrap: break-word;}} td:first-child {{width: 40px; text-align: center;}} td:nth-child(2) {{width: 40px; text-align: center;}} </style>
    {diff_table}
    """

def send_notification_email(yag_instance, subject, html_body, recipients, target_name_for_log='Email'):
    """使用传入的 yagmail 实例发送邮件"""
    # (保持不变)
    adapter_extra = {'target_name': target_name_for_log}
    if not recipients: log_adapter.error("收件人列表为空，无法发送邮件。", extra=adapter_extra); return False
    if not yag_instance: log_adapter.error("Yagmail 实例未初始化，无法发送邮件。", extra=adapter_extra); return False
    if isinstance(recipients, str): recipients = [recipients]
    try:
        recipients_str = ", ".join(recipients)
        log_adapter.info(f"尝试使用 yagmail 发送邮件到 {recipients_str}... Subject: {subject}", extra=adapter_extra)
        yag_instance.send(to=recipients, subject=subject, contents=html_body)
        log_adapter.info("邮件发送成功!", extra=adapter_extra)
        return True
    except yagmail.YagConnectionClosed as e: log_adapter.error(f"Yagmail 连接已关闭，无法发送: {e}", extra=adapter_extra)
    except yagmail.YagAddressError as e: log_adapter.error(f"Yagmail 地址错误 (收件人或发件人?): {e}", extra=adapter_extra)
    except yagmail.YagSMTPError as e:
        log_adapter.error(f"Yagmail 发送邮件时发生SMTP错误: {e}", extra=adapter_extra)
        if "uthentication" in str(e) or "用户名或密码错误" in str(e) or "535" in str(e):
             log_adapter.error("邮件认证失败，请检查 .env 中的 EMAIL_ACCOUNT 和 EMAIL_PASSWORD (应用密码)。", extra=adapter_extra)
    except Exception as e: log_adapter.error(f"使用 yagmail 发送邮件时发生未知错误: {e}", extra=adapter_extra, exc_info=True)
    return False

# --- Main Monitoring Loop (*** 重大修改 ***) ---

def monitor_loop(yag_connection):
    """主监控循环，独立管理每个目标的检查时间"""
    log_adapter.info(f"--- 网页监控启动 (共 {len(MONITOR_TARGETS)} 个目标) ---", extra={'target_name': 'System'})
    # log_adapter.info(f"全局检查间隔: {MONITOR_INTERVAL_SECONDS} 秒", extra={'target_name': 'System'}) # 不再有全局间隔
    log_adapter.info(f"状态文件根目录: {STATE_BASE_DIR}", extra={'target_name': 'System'})

    initial_states = {} # 存储每个目标的上次哈希和内容
    next_check_times = {} # 存储每个目标的下一次检查时间

    # 初始化所有目标的状态和下一次检查时间
    now = datetime.now()
    for target in MONITOR_TARGETS:
        target_name = target.get('name', target['url'])
        target['name'] = target_name
        adapter_extra = {'target_name': target_name}
        state_dir_name = target.get('state_dir', 'monitor_states')
        full_state_dir = os.path.join(STATE_BASE_DIR, state_dir_name)
        ensure_dir_exists(full_state_dir)

        base_filename = get_safe_filename(target_name)
        hash_filepath = os.path.join(full_state_dir, f"{base_filename}.hash")
        content_filepath = os.path.join(full_state_dir, f"{base_filename}.html")
        target['_hash_file'] = hash_filepath
        target['_content_file'] = content_filepath

        previous_hash, previous_content = read_previous_state(hash_filepath, content_filepath, target_name)
        initial_states[target_name] = {'hash': previous_hash, 'content': previous_content}
        # 设置初始检查时间为当前时间，这样第一次循环就会检查
        next_check_times[target_name] = now
        interval = target.get('interval_seconds', 300) # 获取间隔，提供默认值
        log_adapter.info(f"目标 '{target_name}' 初始化完成。检查间隔: {interval}秒。通知邮箱: {', '.join(target.get('recipients', ['未配置']))}", extra=adapter_extra)


    # --- 新的主循环逻辑 ---
    while True:
        now = datetime.now() # 获取当前时间
        checked_target_in_this_cycle = False # 标记本次小循环是否检查了任何目标

        # 遍历所有目标，检查是否到达检查时间
        for target in MONITOR_TARGETS:
            target_name = target['name']
            adapter_extra = {'target_name': target_name}

            # 检查是否到了此目标的检查时间
            if now >= next_check_times.get(target_name, now):
                checked_target_in_this_cycle = True # 标记已检查
                log_adapter.info(f"--- 开始检查目标: {target_name} ---", extra=adapter_extra)

                # --- 执行检查逻辑 (与之前类似) ---
                url = target['url']
                selector = target.get('selector')
                hash_filepath = target['_hash_file']
                content_filepath = target['_content_file']
                wait_for_load_state = target.get('wait_for_load_state')
                wait_timeout = target.get('wait_timeout', 60000)
                target_recipients = target.get('recipients')

                current_content, current_hash = get_target_content_and_hash(
                    url, selector, target_name, wait_for_load_state, wait_timeout
                )

                if current_hash is None or current_content is None:
                    log_adapter.warning("获取内容失败，跳过本次检查的具体处理。", extra=adapter_extra)
                    # 获取失败也应该更新下次检查时间，避免卡住
                else:
                    previous_state = initial_states.get(target_name, {'hash': None, 'content': None})
                    previous_hash = previous_state['hash']
                    previous_content = previous_state['content']

                    if previous_hash is None:
                        log_adapter.info("未找到先前状态，将当前状态存为基准。", extra=adapter_extra)
                        write_current_state(hash_filepath, content_filepath, current_hash, current_content, target_name)
                        initial_states[target_name] = {'hash': current_hash, 'content': current_content}
                    elif current_hash != previous_hash:
                        log_adapter.warning(f"检测到内容变化! 旧哈希: {previous_hash[:10]}..., 新哈希: {current_hash[:10]}...", extra=adapter_extra)
                        if not target_recipients:
                            log_adapter.error("错误: 目标未配置收件人邮箱，无法发送通知。", extra=adapter_extra)
                            write_current_state(hash_filepath, content_filepath, current_hash, current_content, target_name)
                            initial_states[target_name] = {'hash': current_hash, 'content': current_content}
                        else:
                            subject = f"网页监控 [{target_name}]：内容已更新"
                            diff_html = generate_diff_html(previous_content, current_content, target_name)
                            escaped_url = html.escape(url)
                            escaped_selector = html.escape(str(selector)) if selector else "整个渲染后页面"
                            html_body = f"""
                            <html><head><meta charset="utf-8"><title>{html.escape(subject)}</title></head><body>
                            <h2 style="color: #333;">网页监控通知</h2> <p style="font-size: 1.1em;">您监控的目标 <strong>{html.escape(target_name)}</strong> 检测到内容更新。</p> <p><strong>监控URL:</strong> <a href="{escaped_url}" target="_blank">{escaped_url}</a></p> <p><strong>监控区域 (CSS Selector):</strong> <code>{escaped_selector}</code></p> <hr style="border: none; border-top: 1px solid #eee;">{diff_html} <hr style="border: none; border-top: 1px solid #eee; margin-top: 20px;"> <p style="font-size: 0.8em; color: #888;">(此邮件由 Python 网页监控脚本自动发送)</p>
                            </body></html>
                            """
                            if send_notification_email(yag_connection, subject, html_body, target_recipients, target_name):
                                write_current_state(hash_filepath, content_filepath, current_hash, current_content, target_name)
                                initial_states[target_name] = {'hash': current_hash, 'content': current_content}
                            else:
                                log_adapter.error("邮件发送失败，状态未更新，将在下次检查时重试。", extra=adapter_extra)
                    else:
                        log_adapter.info("内容无变化。", extra=adapter_extra)

                # --- 更新此目标的下一次检查时间 ---
                interval_seconds = target.get('interval_seconds', 300) # 获取当前目标的间隔
                next_check_times[target_name] = datetime.now() + timedelta(seconds=interval_seconds)
                log_adapter.info(f"目标 '{target_name}' 下次检查时间: {next_check_times[target_name].strftime('%Y-%m-%d %H:%M:%S')}", extra=adapter_extra)
                log_adapter.info(f"--- 完成检查目标: {target_name} ---", extra=adapter_extra)
                # --- 在连续检查多个目标之间稍作停顿，减轻瞬时压力 ---
                time.sleep(1) # 短暂休眠1秒

        # --- 短暂休眠，避免主循环空转占用过多 CPU ---
        # 如果本次小循环没有检查任何目标，则休眠长一点时间
        sleep_time = MIN_CHECK_INTERVAL if not checked_target_in_this_cycle else 1
        # log_adapter.debug(f"主循环休眠 {sleep_time} 秒...", extra={'target_name':'System'}) # Debug 用
        time.sleep(sleep_time)


# --- Script Entry Point ---
if __name__ == "__main__":
    yag = None
    try:
        # --- Basic Configuration Checks ---
        if not MONITOR_TARGETS:
             log_adapter.critical("错误：监控目标列表 MONITOR_TARGETS 为空！", extra={'target_name': 'System'})
             exit(1)
        all_targets_valid = True
        for i, target_config in enumerate(MONITOR_TARGETS):
            target_id_for_error = target_config.get('name', f"未命名目标 {i+1}")
            if not target_config.get('url'):
                 log_adapter.critical(f"错误：监控目标 '{target_id_for_error}' 未配置 'url'！", extra={'target_name': 'System'}); all_targets_valid = False
            recipients = target_config.get('recipients')
            if not recipients:
                log_adapter.critical(f"错误：监控目标 '{target_id_for_error}' 未配置收件人 ('recipients')！", extra={'target_name': 'System'}); all_targets_valid = False
            elif not isinstance(recipients, list) or not recipients:
                 log_adapter.critical(f"错误：监控目标 '{target_id_for_error}' 的 'recipients' 必须是非空列表！", extra={'target_name': 'System'}); all_targets_valid = False
            interval = target_config.get('interval_seconds')
            if interval is None:
                 log_adapter.critical(f"错误：监控目标 '{target_id_for_error}' 未配置检查间隔 ('interval_seconds')！", extra={'target_name': 'System'}); all_targets_valid = False
            elif not isinstance(interval, int) or interval <= 0:
                 log_adapter.critical(f"错误：监控目标 '{target_id_for_error}' 的 'interval_seconds' 必须是正整数！", extra={'target_name': 'System'}); all_targets_valid = False
        if not all_targets_valid:
             exit(1)

        # --- Initialize Yagmail ---
        try:
             log_adapter.info(f"正在初始化 yagmail 连接 (User: {EMAIL_ACCOUNT}, Host: {SMTP_SERVER}:{SMTP_PORT})...", extra={'target_name': 'System'})
             yag_kwargs = {'user': EMAIL_ACCOUNT, 'password': EMAIL_PASSWORD, 'host': SMTP_SERVER, 'port': SMTP_PORT}
             if SMTP_PORT == 465: yag_kwargs['smtp_ssl'] = True
             # elif SMTP_PORT == 587: pass # yagmail 通常自动处理 TLS on 587
             yag = yagmail.SMTP(**yag_kwargs)
             log_adapter.info("Yagmail 初始化成功。", extra={'target_name': 'System'})
        except Exception as yag_init_err:
             log_adapter.critical(f"Yagmail 初始化失败: {yag_init_err}", extra={'target_name': 'System'}, exc_info=True)
             log_adapter.critical("请检查 .env 文件中的邮件服务器、端口、账号、密码/应用密码以及网络连接。", extra={'target_name': 'System'})
             exit(1)

        # --- Run Playwright Installation Check ---
        try:
            with sync_playwright() as p: browser = p.chromium.launch(headless=True); browser.close()
            log_adapter.info("Playwright 环境检查通过。", extra={'target_name': 'System'})
        except Exception as install_err:
             log_adapter.critical(f"Playwright 环境似乎未正确安装或配置。错误: {install_err}", extra={'target_name': 'System'})
             log_adapter.critical("请确保已运行 'pip install playwright' 和 'playwright install'。", extra={'target_name': 'System'})
             if yag: yag.close(); exit(1)

        # --- Send Startup Notifications ---
        log_adapter.info("发送启动通知...", extra={'target_name': 'System'})
        startup_notifications_failed = False
        for target in MONITOR_TARGETS:
            target_name = target['name']
            target_recipients = target.get('recipients')
            if target_recipients:
                startup_subject = f"监控任务启动：[{target_name}] (间隔: {target.get('interval_seconds', 'N/A')}s)"
                startup_body = f"""
                <html><body> <p>网页监控脚本已启动。</p> <p>已开始监控任务：<strong>{html.escape(target_name)}</strong></p> <p>监控URL: {html.escape(target.get('url','N/A'))}</p> <p>检查间隔: {target.get('interval_seconds', 'N/A')} 秒</p> <p>通知将发送给: {', '.join(target_recipients)}</p> </body></html>
                """
                if not send_notification_email(yag, startup_subject, startup_body, target_recipients, target_name):
                    log_adapter.error(f"启动通知发送失败: {target_name}", extra={'target_name': target_name})
                    startup_notifications_failed = True
            else: log_adapter.warning(f"目标 '{target_name}' 没有收件人，无法发送启动通知。", extra={'target_name': target_name})
        if startup_notifications_failed: log_adapter.warning("部分启动通知发送失败，但监控将继续。", extra={'target_name': 'System'})
        else: log_adapter.info("所有启动通知已发送（或无需发送）。", extra={'target_name': 'System'})

        # --- Start Monitoring Loop ---
        monitor_loop(yag)

    except KeyboardInterrupt:
        log_adapter.info("监控被手动中断。", extra={'target_name': 'System'})
    except Exception as e:
        log_adapter.critical(f"监控主程序发生严重错误: {e}", extra={'target_name': 'System'}, exc_info=True)
        if yag and ADMIN_EMAIL:
           try:
               error_subject = "监控脚本严重错误退出"
               error_body = f"监控脚本遇到严重错误并意外退出。\n\n错误信息:\n<pre>{html.escape(traceback.format_exc())}</pre>"
               send_notification_email(yag, error_subject, error_body, [ADMIN_EMAIL], 'SystemError')
               log_adapter.info(f"已尝试向管理员邮箱 {ADMIN_EMAIL} 发送错误报告。", extra={'target_name': 'System'})
           except Exception as final_email_err:
               log_adapter.error(f"尝试发送最终错误邮件给管理员失败: {final_email_err}", extra={'target_name': 'System'})

    finally:
        if yag:
            log_adapter.info("正在关闭 yagmail 连接...", extra={'target_name': 'System'})
            try:
                yag.close()
                log_adapter.info("Yagmail 连接已关闭。", extra={'target_name': 'System'})
            except Exception as close_err:
                log_adapter.error(f"关闭 yagmail 连接时出错: {close_err}", extra={'target_name': 'System'})
        log_adapter.info("监控脚本退出。", extra={'target_name': 'System'})
