
# 威科夫异动监控 - 云端部署指南 (Koyeb 免费版)

由于本地或美国 VPS 受到币安的严格地区封锁，我们推荐将程序部署到 **Koyeb** 云平台。它提供**免费**的运算资源，并且可以选择**法兰克福 (Frankfurt)** 或 **新加坡 (Singapore)** 节点，完美绕过屏蔽。

---

## 第一步：准备代码仓库

您需要将当前文件夹的所有代码上传到一个 **GitHub** 仓库中。
(如果您已经有 GitHub 仓库，可以直接跳过此步的创建部分)

1.  登录 [GitHub](https://github.com/) 并创建一个新仓库（例如命名为 `binance-monitor`）。
2.  将本地代码推送到该仓库。确保仓库中包含以下核心文件：
    -   `Dockerfile`
    -   `requirements.txt`
    -   `wyckoff_monitor.py`

---

## 第二步：主要部署流程 (Koyeb)

1.  **注册/登录**：
    -   访问 [Koyeb 官网](https://www.koyeb.com/) 并在右上角点击 Sign Up / Login (支持 GitHub 快捷登录)。

2.  **创建服务 (Create Service)**：
    -   在控制台首页，点击 **Create App** (或 Create Service)。
    -   选择 **GitHub** 作为部署源。
    -   授权后，在列表中选择您刚才创建的 `binance-monitor` 仓库。

3.  **配置服务 (Configure)**：
    -   **Repository**: 保持默认 (main 分支)。
    -   **Builder**: 选择 **Dockerfile**。
    -   **Compute (核心步骤)**:
        -   **Instance Type**: 选择 **Free** (Nano, 0.5 vCPU, 512MB RAM)。
        -   **Regions (关键)**: 请务必选择 **Frankfurt (Germany)** 或 **Singapore**。**千万不要选 Washington D.C.**。

4.  **环境变量 (Environment Variables)**：
    -   点击 Advanced 或 Environment Variables 区域。
    -   如果您不想把 Webhook 地址写死在代码里，可以在这里添加变量：
        -   Key: `WEBHOOK_URL`
        -   Value: `您的钉钉或飞书 Webhook 地址`
    *(注：如果代码里已经写了 Webhook，这步可跳过，但推荐通过环境变量传入以保安全)*

5.  **开始部署**：
    -   点击页面底部的 **Deploy** 按钮。

---

## 第三步：验证状态

1.  等待构建 (Build) 完成，通常需要 1-2 分钟。
2.  当状态变为 **Healthy** (绿色) 时，点击 Runtime Logs。
3.  您应该能看到类似以下的日志：
    ```
    INFO - 正在加载市场信息...
    INFO - 市场加载完毕...
    INFO - [STARTED] 实时监控已启动...
    ```
4.  如果没有出现 451 错误，恭喜您，机器人已在云端 7x24 小时为您工作！

---

## Q&A

*   **是免费的吗？**
    *   是的，Koyeb 提供每月一定额度的免费计算资源，运行这个轻量级脚本绰绰有余。
*   **如何停止？**
    *   在 Koyeb 控制台点击 Pause Service 即可暂停运行。
*   **如何更新代码？**
    *   只要您向 GitHub 仓库 push 新代码，Koyeb 会自动触发重新部署。
