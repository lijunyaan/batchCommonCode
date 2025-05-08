# batchCommonCode

python -m venv .venv # 使用系统 python 创建新的虚拟环境
python3 -m venv .venv # 使用系统 python 创建新的虚拟环境

.venv/Scripts/activate # 激活虚拟环境

pip install -r requirements.txt # 安装依赖
pip install tkinterdnd2-universal

# 打包
PyInstaller --onefile --noconsole --icon=app.ico FileRenamer_v1.1.py
PyInstaller --onefile --noconsole --icon=app.ico --add-data "D:\\codework\\batchCommonCode\\.venv\\Lib\\site-packages\\tkinterdnd2\\tkdnd:tkinterdnd2/tkdnd" FileRenamer_v1.1.py
