# -*- coding: utf-8 -*-
import time
import hashlib
import smtplib
import logging
import os
import difflib
import html # 用于 HTML 转义
from email.mime.text import MIMEText
from email.header import Header
from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeoutError, Error as PlaywrightError

# --- 配置区 ---
"""
安装依赖:
    pip install playwright
    playwright install
配置脚本:
    MONITOR_TARGETS: 这是核心配置。
    为你想要监控的每个网站/区域添加一个字典。
    name: 任务的易记名称。
    url: 目标网址。
    selector: 定位内容的CSS选择器 (用浏览器开发者工具获取)。设为 None 监控整个页面。
    recipients: 关键！ 这是一个列表，包含当这个特定目标发生变化时需要通知的邮箱地址。
    state_dir: 状态文件目录。
    wait_for_load_state, wait_timeout: Playwright 相关参数，根据目标网站调整。
    邮件发件人设置: 配置 SMTP_SERVER, SMTP_PORT, USE_SSL, EMAIL_ACCOUNT, EMAIL_PASSWORD (应用专用密码), SENDER_NAME。
"""
# 1. 监控目标列表 (*** 在这里添加或修改你要监控的网站和区域 ***)
#    每个目标现在包含自己的 'recipients' 列表
import os

# 获取当前文件的目录路径
current_dir = os.path.dirname(__file__)

# 更新 MONITOR_TARGETS 中的 state_dir 路径
MONITOR_TARGETS = [
    {
        "name": "动态新闻监控",
        "url": "https://www.sbxh.org.cn/news",
        "selector": "#news-list",
        "recipients": ["369996890@qq.com",],
        "state_dir": os.path.join(current_dir, "monitor_states"),
        "wait_for_load_state": "networkidle",
        "wait_timeout": 60000,
    },
    # {
    #     "name": "静态公告页面",
    #     "url": "YOUR_STATIC_SITE_URL",      # *** 另一个目标网站URL (普通HTML) ***
    #     "selector": "div.announcements",    # *** 此页面的CSS选择器 ***
    #     "recipients": ["admin@example.com"], # *** 此目标的收件人列表 ***
    #     "state_dir": "monitor_states",
    #     # 对于静态页面，可以不使用 Playwright 特定的等待选项，或者使用 'load'/'domcontentloaded'
    #     "wait_for_load_state": "load",
    #     "wait_timeout": 30000,
    # },
    # --- 可以继续添加更多监控目标 ---
    # {
    #     "name": "监控整个页面",
    #     "url": "https://specific-page.com/status",
    #     "selector": None, # 监控整个页面
    #     "recipients": ["monitor-alerts@example.com"],
    #     "state_dir": "monitor_states",
    #     "wait_for_load_state": "load",
    #     "wait_timeout": 30000,
    # },
]

# 2. 全局监控设置
MONITOR_INTERVAL_SECONDS = 300      # 监控时间间隔（秒）
USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36" # Playwright 会用到
REQUEST_TIMEOUT = 30                # 主要用于邮件发送的超时

# 3. 邮件发件人设置 (*** 需要修改为你自己的邮箱信息 ***)
SMTP_SERVER = "smtp.163.com"        # 例如: "smtp.qq.com", "smtp.gmail.com"
SMTP_PORT = 465                     # SMTP端口 (QQ/Gmail SSL: 465)
USE_SSL = True                      # 如果端口是465，设为True
EMAIL_ACCOUNT = "lijunyaan@163.com"      # 发件人邮箱账号
EMAIL_PASSWORD = "ljremanlei.2302" # 发件人邮箱密码或应用专用密码 (推荐)
SENDER_NAME = "网页监控机器人"      # 发件人显示名称
# 注意：全局的 RECIPIENT_EMAILS 已被移除

# 4. 日志设置
LOG_FILE = "monitor.log"
LOG_LEVEL = logging.INFO # 日志级别 (DEBUG, INFO, WARNING, ERROR, CRITICAL)

# --- 配置区结束 ---

# --- 日志配置 ---
logging.basicConfig(
    level=LOG_LEVEL,
    format='%(asctime)s - %(levelname)s - [%(target_name)s] - %(message)s',
    handlers=[
        logging.FileHandler(LOG_FILE, encoding='utf-8'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)
# 创建一个自定义Adapter来轻松添加 target_name 到日志记录中
class TargetLogAdapter(logging.LoggerAdapter):
    def process(self, msg, kwargs):
        # 如果日志记录的 extra 字典中没有 'target_name'，则添加默认值
        if 'target_name' not in self.extra:
            self.extra['target_name'] = 'System' # 或其他默认值
        # 将 target_name 添加到消息前面（如果需要且未手动添加）
        # 或者保持原样，依赖 format 配置
        return msg, kwargs

log_adapter = TargetLogAdapter(logger, {'target_name': 'System'})


# --- 辅助函数 ---

def get_safe_filename(name_or_url):
    """根据名称或URL生成一个安全的文件名"""
    sanitized = name_or_url.replace("http://", "").replace("https://", "")
    sanitized = "".join([c if c.isalnum() or c in ('-', '_', '.') else '_' for c in sanitized])
    return sanitized[:100] # 限制最大长度

def ensure_dir_exists(dir_path):
    """确保目录存在，如果不存在则创建"""
    if not os.path.exists(dir_path):
        try:
            os.makedirs(dir_path)
            log_adapter.info(f"创建状态目录: {dir_path}", extra={'target_name': 'System'})
        except OSError as e:
            log_adapter.error(f"无法创建状态目录: {dir_path}, 错误: {e}", extra={'target_name': 'System'}, exc_info=True)
            raise # 无法创建目录是严重问题，抛出异常

# --- 核心功能函数 ---

def get_target_content_and_hash(url, selector, target_name, wait_for_load_state=None, wait_timeout=60000):
    """使用 Playwright 获取动态加载的内容及其哈希值"""
    adapter_extra = {'target_name': target_name}
    log_adapter.info(f"开始使用 Playwright 获取内容: {url}", extra=adapter_extra)
    content_to_check = None
    current_hash = None

    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True) # 使用无头模式
            page = browser.new_page(user_agent=USER_AGENT)

            log_adapter.info(f"导航到: {url}", extra=adapter_extra)
            page.goto(url, timeout=wait_timeout, wait_until=wait_for_load_state or 'load')

            log_adapter.info(f"等待选择器加载: '{selector or '整个页面'}' (最长 {wait_timeout} ms)", extra=adapter_extra)

            if selector:
                try:
                    target_element = page.locator(selector).first
                    # 等待元素可见，这是动态内容加载完成的一个好迹象
                    target_element.wait_for(state="visible", timeout=wait_timeout)
                    # 获取元素内部的 HTML，这通常比纯文本更能反映结构变化
                    content_to_check = target_element.inner_html()
                    log_adapter.info(f"成功定位并提取选择器 '{selector}' 的内容", extra=adapter_extra)

                except PlaywrightTimeoutError:
                    log_adapter.error(f"等待选择器 '{selector}' 超时 ({wait_timeout} ms)", extra=adapter_extra)
                    browser.close()
                    return None, None
                except PlaywrightError as e:
                    log_adapter.error(f"定位选择器 '{selector}' 时出错: {e}", extra=adapter_extra)
                    browser.close()
                    return None, None
            else:
                # 获取整个渲染后的页面内容
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
    adapter_extra = {'target_name': target_name}
    previous_hash = None
    previous_content = None

    if os.path.exists(hash_filepath):
        try:
            with open(hash_filepath, 'r', encoding='utf-8') as f:
                previous_hash = f.read().strip()
        except IOError as e:
            log_adapter.error(f"读取哈希文件失败: {hash_filepath}, 错误: {e}", extra=adapter_extra)

    if os.path.exists(content_filepath):
        try:
            with open(content_filepath, 'r', encoding='utf-8') as f:
                previous_content = f.read()
        except IOError as e:
            log_adapter.error(f"读取旧内容文件失败: {content_filepath}, 错误: {e}", extra=adapter_extra)

    if previous_hash:
         log_adapter.info(f"读取到上次哈希: {previous_hash[:10]}...", extra=adapter_extra)
    else:
         log_adapter.info("未找到上次状态文件，将首次获取内容作为基准", extra=adapter_extra)

    return previous_hash, previous_content

def write_current_state(hash_filepath, content_filepath, current_hash, current_content, target_name):
    """将当前哈希和内容写入文件"""
    adapter_extra = {'target_name': target_name}
    try:
        with open(hash_filepath, 'w', encoding='utf-8') as f:
            f.write(current_hash)
        with open(content_filepath, 'w', encoding='utf-8') as f:
            # 确保写入的是字符串
            f.write(str(current_content) if current_content is not None else "")
        log_adapter.info(f"成功将新状态写入文件 ({os.path.basename(hash_filepath)}, {os.path.basename(content_filepath)})", extra=adapter_extra)
    except IOError as e:
        log_adapter.error(f"写入状态文件失败: {hash_filepath} 或 {content_filepath}, 错误: {e}", extra=adapter_extra)
    except Exception as e:
         log_adapter.error(f"写入状态时发生未知错误: {e}", extra=adapter_extra, exc_info=True)


def generate_diff_html(old_content, new_content, target_name):
    """使用 difflib 生成 HTML 格式的差异对比"""
    adapter_extra = {'target_name': target_name}
    if old_content is None or new_content is None :
        log_adapter.info("缺少旧内容或新内容，无法生成差异对比。", extra=adapter_extra)
        new_content_escaped = html.escape(str(new_content)) if new_content is not None else "<i>(无法获取当前内容)</i>"
        return f"<p><b>检测到变化（无法生成差异对比）：</b></p><pre>{new_content_escaped}</pre>"

    log_adapter.info("正在生成内容差异...", extra=adapter_extra)
    # 确保比较的是字符串列表
    old_lines = str(old_content).splitlines()
    new_lines = str(new_content).splitlines()

    diff = difflib.HtmlDiff(wrapcolumn=80)
    try:
        diff_table = diff.make_file(
            old_lines,
            new_lines,
            fromdesc="旧内容",
            todesc="新内容",
            context=True,
            numlines=5
        )
        log_adapter.info("内容差异生成完毕。", extra=adapter_extra)
    except Exception as e:
        log_adapter.error(f"生成差异对比时出错: {e}", extra=adapter_extra, exc_info=True)
        # 出错时返回简单提示和新内容
        new_content_escaped = html.escape(str(new_content))
        return f"<p><b>检测到变化（生成差异对比时出错）：</b></p><p>错误信息：{html.escape(str(e))}</p><p><b>新内容：</b></p><pre>{new_content_escaped}</pre>"

    # 返回包含CSS样式的HTML diff表格
    return f"""
    <p><b>检测到内容变化（差异对比）：</b></p>
    <style>
        table.diff {{font-family: Courier, monospace; border: solid 1px #ccc; border-collapse: collapse; width: 98%; margin: 10px auto;}}
        tbody {{font-size: 0.9em;}}
        .diff_header {{background-color:#f0f0f0; padding: 4px; font-weight: bold;}}
        td.diff_header {{text-align:right; padding-right: 10px;}}
        .diff_next {{background-color:#ddd;}}
        .diff_add {{background-color:#ddffdd;}} /* 浅绿表示增加 */
        .diff_chg {{background-color:#ffffcc;}} /* 浅黄表示修改 */
        .diff_sub {{background-color:#ffdddd;}} /* 浅红表示删除 */
        td {{padding: 2px 4px; vertical-align: top; white-space: pre-wrap; word-wrap: break-word;}}
        td:first-child {{width: 40px; text-align: center;}} /* 行号列 */
        td:nth-child(2) {{width: 40px; text-align: center;}} /* 行号列 */
    </style>
    {diff_table}
    """

def send_notification_email(subject, html_body, recipients):
    """发送 HTML 格式的邮件通知给指定的收件人列表"""
    adapter_extra = {'target_name': 'Email'}
    if not recipients:
        log_adapter.error("收件人列表为空，无法发送邮件。", extra=adapter_extra)
        return False

    # 确保 recipients 是一个列表
    if isinstance(recipients, str):
        recipients = [recipients]

    message = MIMEText(html_body, 'html', 'utf-8')
    message['From'] = Header(f"{SENDER_NAME} <{EMAIL_ACCOUNT}>", 'utf-8')
    # 收件人头信息最好只包含地址，避免特殊字符问题
    message['To'] = ", ".join(recipients)
    message['Subject'] = Header(subject, 'utf-8')

    try:
        recipients_str = ", ".join(recipients)
        log_adapter.info(f"尝试发送邮件到 {recipients_str}...", extra=adapter_extra)
        if USE_SSL:
            server = smtplib.SMTP_SSL(SMTP_SERVER, SMTP_PORT, timeout=REQUEST_TIMEOUT)
        else:
            server = smtplib.SMTP(SMTP_SERVER, SMTP_PORT, timeout=REQUEST_TIMEOUT)
            # 如果需要 TLS (例如端口 587)，取消注释
            # server.ehlo()
            # server.starttls()
            # server.ehlo()

        server.login(EMAIL_ACCOUNT, EMAIL_PASSWORD)
        server.sendmail(EMAIL_ACCOUNT, recipients, message.as_string())
        server.quit()
        log_adapter.info("邮件发送成功!", extra=adapter_extra)
        return True
    except smtplib.SMTPAuthenticationError as e:
        log_adapter.error(f"邮件认证失败: {e}", extra=adapter_extra)
        log_adapter.error("请检查邮箱账号和密码（或应用专用密码）是否正确。", extra=adapter_extra)
    except smtplib.SMTPException as e:
        log_adapter.error(f"发送邮件时发生SMTP错误: {e}", extra=adapter_extra)
    except Exception as e:
        log_adapter.error(f"发送邮件时发生未知错误: {e}", extra=adapter_extra, exc_info=True)
    return False


# --- 主监控循环 ---
def monitor_loop():
    """主监控循环，遍历所有监控目标"""
    log_adapter.info(f"--- 网页监控启动 (共 {len(MONITOR_TARGETS)} 个目标) ---", extra={'target_name': 'System'})
    log_adapter.info(f"全局检查间隔: {MONITOR_INTERVAL_SECONDS} 秒", extra={'target_name': 'System'})

    initial_states = {}
    for target in MONITOR_TARGETS:
        target_name = target.get('name', target['url']) # 如果没名字，用URL代替
        target['name'] = target_name # 确保存储了名字
        adapter_extra = {'target_name': target_name}
        state_dir = target.get('state_dir', 'monitor_states')
        ensure_dir_exists(state_dir)

        base_filename = get_safe_filename(target_name)
        hash_filepath = os.path.join(state_dir, f"{base_filename}.hash")
        content_filepath = os.path.join(state_dir, f"{base_filename}.html")
        target['_hash_file'] = hash_filepath
        target['_content_file'] = content_filepath

        previous_hash, previous_content = read_previous_state(hash_filepath, content_filepath, target_name)
        initial_states[target_name] = {
            'hash': previous_hash,
            'content': previous_content
        }
        log_adapter.info(f"目标 '{target_name}' 初始化完成。通知邮箱: {', '.join(target.get('recipients', ['未配置']))}", extra=adapter_extra)


    while True:
        log_adapter.info(f"--- 开始新一轮检查 ({len(MONITOR_TARGETS)} 个目标) ---", extra={'target_name': 'System'})
        for target in MONITOR_TARGETS:
            target_name = target['name']
            adapter_extra = {'target_name': target_name}
            url = target['url']
            selector = target.get('selector')
            hash_filepath = target['_hash_file']
            content_filepath = target['_content_file']
            wait_for_load_state = target.get('wait_for_load_state')
            wait_timeout = target.get('wait_timeout', 60000)
            target_recipients = target.get('recipients') # 获取此目标的收件人

            # 获取当前内容和哈希
            current_content, current_hash = get_target_content_and_hash(
                url, selector, target_name, wait_for_load_state, wait_timeout
            )

            if current_hash is None or current_content is None:
                log_adapter.warning("获取内容失败，跳过本次检查。", extra=adapter_extra)
                continue

            # 获取上次状态
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
                    # 即使不发邮件，也应该更新状态，避免下次重复误报（除非需要强制重试）
                    # 如果需要强制重试直到邮件发送成功，则不应执行下面的写状态和更新内存状态
                    # 当前逻辑：不发邮件，但更新状态
                    write_current_state(hash_filepath, content_filepath, current_hash, current_content, target_name)
                    initial_states[target_name] = {'hash': current_hash, 'content': current_content}
                    continue # 处理下一个目标

                subject = f"网页监控 [{target_name}]：内容已更新"
                diff_html = generate_diff_html(previous_content, current_content, target_name)

                # 构建邮件正文
                escaped_url = html.escape(url)
                escaped_selector = html.escape(str(selector)) if selector else "整个渲染后页面"
                html_body = f"""
                <html>
                <head>
                    <meta charset="utf-8">
                    <title>{html.escape(subject)}</title>
                </head>
                <body>
                    <h2 style="color: #333;">网页监控通知</h2>
                    <p style="font-size: 1.1em;">您监控的目标 <strong>{html.escape(target_name)}</strong> 检测到内容更新。</p>
                    <p><strong>监控URL:</strong> <a href="{escaped_url}" target="_blank">{escaped_url}</a></p>
                    <p><strong>监控区域 (CSS Selector):</strong> <code>{escaped_selector}</code></p>
                    <hr style="border: none; border-top: 1px solid #eee;">
                    {diff_html}
                    <hr style="border: none; border-top: 1px solid #eee; margin-top: 20px;">
                    <p style="font-size: 0.8em; color: #888;">(此邮件由 Python 网页监控脚本自动发送)</p>
                </body>
                </html>
                """

                # 发送邮件给此目标的指定收件人
                if send_notification_email(subject, html_body, target_recipients):
                    # 邮件发送成功后，更新状态文件和内存中的状态
                    write_current_state(hash_filepath, content_filepath, current_hash, current_content, target_name)
                    initial_states[target_name] = {'hash': current_hash, 'content': current_content}
                else:
                    log_adapter.error("邮件发送失败，状态未更新，将在下次检查时重试。", extra=adapter_extra)
                    # 注意：不更新状态意味着下次还会检测到变化并尝试发送

            else:
                log_adapter.info("内容无变化。", extra=adapter_extra)

            # 在处理完一个目标后稍微暂停，避免对服务器造成过大压力（可选）
            # time.sleep(0.5)

        log_adapter.info(f"本轮检查完成，等待 {MONITOR_INTERVAL_SECONDS} 秒...", extra={'target_name': 'System'})
        time.sleep(MONITOR_INTERVAL_SECONDS)


# --- 脚本入口 ---
if __name__ == "__main__":
    try:
        # --- 基本配置检查 ---
        if not MONITOR_TARGETS:
             log_adapter.critical("错误：监控目标列表 MONITOR_TARGETS 为空！请添加至少一个监控目标。", extra={'target_name': 'System'})
             exit(1)

        # 检查每个目标是否配置了收件人
        all_targets_have_recipients = True
        for i, target_config in enumerate(MONITOR_TARGETS):
            target_id_for_error = target_config.get('name', f"Target {i+1} at URL {target_config.get('url', 'N/A')}")
            if not target_config.get('url'):
                 log_adapter.critical(f"错误：监控目标 '{target_id_for_error}' 未配置 'url'！", extra={'target_name': 'System'})
                 all_targets_have_recipients = False # 标记为失败
            if not target_config.get('recipients'):
                log_adapter.critical(f"错误：监控目标 '{target_id_for_error}' 未配置收件人邮箱列表 ('recipients')！", extra={'target_name': 'System'})
                all_targets_have_recipients = False # 标记为失败
            elif not isinstance(target_config['recipients'], list) or not target_config['recipients']:
                 log_adapter.critical(f"错误：监控目标 '{target_id_for_error}' 的 'recipients' 必须是一个非空的列表！", extra={'target_name': 'System'})
                 all_targets_have_recipients = False # 标记为失败

        if not all_targets_have_recipients:
             exit(1) # 如果有目标配置不正确则退出

        # 检查邮件发件人配置
        if not EMAIL_ACCOUNT or not EMAIL_PASSWORD:
             log_adapter.critical("错误：发件人邮箱账号 ('EMAIL_ACCOUNT') 或密码/应用密码 ('EMAIL_PASSWORD') 未配置！", extra={'target_name': 'System'})
             exit(1)

        # --- 运行 Playwright 安装检查（可选，但推荐） ---
        try:
            with sync_playwright() as p:
                # 尝试启动一个浏览器实例以确保安装正常
                browser = p.chromium.launch(headless=True)
                browser.close()
            log_adapter.info("Playwright 环境检查通过。", extra={'target_name': 'System'})
        except Exception as install_err:
             log_adapter.critical(f"Playwright 环境似乎未正确安装或配置。错误: {install_err}", extra={'target_name': 'System'})
             log_adapter.critical("请确保已运行 'pip install playwright' 和 'playwright install'。", extra={'target_name': 'System'})
             exit(1)

        # --- 启动监控循环 ---
        monitor_loop()

    except KeyboardInterrupt:
        log_adapter.info("监控被手动中断。", extra={'target_name': 'System'})
    except Exception as e:
        # 捕获未预料到的主程序错误
        logging.critical(f"监控主程序发生严重错误: {e}", exc_info=True) # 使用 root logger 记录
        # 可以考虑在这里也尝试发送一个全局错误邮件给管理员
        send_notification_email("监控脚本严重错误", f"<pre>{traceback.format_exc()}</pre>", ["369996890@qq.com"])
