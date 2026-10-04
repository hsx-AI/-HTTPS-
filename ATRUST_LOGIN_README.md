# HTTPS 短信接码与自动登录

## 第一次配置

1. 双击 `setup.bat`。配置短信服务时输入项目取码密钥；不要使用 Android App 的 `device_token`。
2. 复制 `atrust_config.example.json` 为 `atrust_config.json`，填入 aTrust 手机号。`smsSenderContains` 可填写短信发送号码/名称的一部分；留空时按项目密钥权限读取任意发送方的新码。
3. 复制 `ecs_login_config.example.json` 为 `ecs_login_config.json`，填写 AE 平台用户名和密码。

凭据保存在本地配置文件，已加入 `.gitignore`。限制这些文件的访问权限，不要上传或分享。

## 完整流程

运行：

```powershell
python .\main.py
```

程序会自动完成 aTrust 登录、请求并等待新短信、登录 AE 协调平台、下载 Excel 并按“文件编号”更新 SQLite。短信来源及游标用于区分新码与未过期旧码。手机端 App 和电脑端脚本使用不同密钥：手机用 `device_token` 上传，电脑脚本用项目取码密钥读取。

也可单独运行 aTrust 流程：

```powershell
python .\atrust_auto_login.py --phone 你的手机号
```

或仅同步 AE 数据：

```powershell
python .\ecs_sync.py
```

常驻同步程序：

```powershell
python .\scheduler.py
```

## HTTPS 连接诊断

设置向导会检查服务器健康状态和项目密钥认证。若认证失败，请确认使用 `credentials.json` 的 `clients.default`，以及服务器端该项目允许读取对应短信发送方。脚本日志不会打印验证码密钥。

不需要 USB、Android Accessory、PC 短信接收服务或管理员权限。手机需保持开机、联网，并允许 App 在后台接收和转发短信。
