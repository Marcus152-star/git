GenFollower 询盘路由器 0.4.1（Windows 64 位便携版）
=======================================================

一、当前版本能做什么

读取小翼 CRM 导出的客户 Excel，以只读方式下载 Zoho 邮件，并给出建议负责人。
当前版本不会发送或转发邮件，也不会修改小翼 CRM；Zoho邮件不会被标记为已读。

推荐直接双击 GenFollower-Inquiry-Router-GUI.exe 使用可视化客户端。
inquiry-router.exe 是保留给高级用户的命令行版本。

二、首次配置

1. 双击 GenFollower-Inquiry-Router-GUI.exe。
2. 在界面顶部填写 Chloe、Nicole、Ella 的完整邮箱。
3. 填写程序启用前已经分配完成的普通新询盘累计数。
4. 点击“保存配置”。

也可以继续使用记事本编辑同目录的 config.local.json。

“普通新询盘”必须同时满足：
- 确认是真实询盘；
- 小翼 CRM 中没有客户记录；
- 不属于独家市场。

例如此前已经分配了 17 封普通新询盘，就填写 17；下一封将按第 18 封继续。
如果希望从全新的第一圈开始，填写 0。

三、检查配置和轮转起点

在客户端中可以直接查看“当前正式计数”，也可以填写数字后点击“设置正式计数”。

以下命令行方法仅供高级用户使用：

在本文件夹空白处按住 Shift 并单击鼠标右键，选择“在终端中打开”，执行：

.\inquiry-router.exe state --config .\config.local.json --state .\data\router_state.sqlite3

第一次执行会创建状态数据库。输出数字应等于 initial_standard_inquiry_count。

如果数据库已经创建，之后需要校正轮转起点，请执行：

.\inquiry-router.exe state --config .\config.local.json --state .\data\router_state.sqlite3 --set-count 17

把 17 换成实际累计数量。不要通过删除数据库来校正正式计数。

四、连接Zoho（影子模式）

1. 在Zoho区域填写已生成的应用专用密码。
2. 保持服务器为 imappro.zoho.com:993 和 smtppro.zoho.com:465，点击“保存Zoho设置”。
3. 密码使用当前Windows账户加密保存，不会写入config.local.json。
4. 点击“测试收件连接”和“测试发件连接（不发信）”。后者不会真的发送邮件。
5. 点击“查看最近20封邮件”只核对时间、发件人和主题，不会判断或分配这些历史邮件。
6. 选择客户Excel后，点击“开始/继续自动监控”。首次使用只读取此后到达的新邮件；已有起点时继续原进度。
7. 客户端保持打开时每60秒自动检查一次，新结果会持续追加；也可手动点击“读取监控后的新邮件”。
8. “清空预览结果”只清除屏幕列表，不会改变邮件监控进度、模拟轮转位置或正式计数。

自动监控使用独立的模拟轮转计数，跨批次持续累计但不改变正式计数。客户端关闭后不会继续后台运行。

五、检查客户 Excel

客户端支持同时选择多份客户 Excel。点击“选择 Excel（可多选）”后，按住 Ctrl 逐个选择，或按住 Shift 连续选择，然后点击“打开”。程序会把这些文件合并成一个只读客户库。

如果相同邮箱在不同文件中对应不同负责人，程序会标记为“需要人工确认”，不会自动选择其中一个负责人。

以下命令行方法仅供高级用户使用：

.\inquiry-router.exe inspect-customers --customers "C:\路径\客户导出1.xlsx" "C:\路径\客户导出2.xlsx"

六、预览测试邮件

客户端操作：选择客户 Excel，选择 examples 文件夹，然后点击“预览分配”。

以下命令行方法仅供高级用户使用：

.\inquiry-router.exe route-eml --customers "C:\路径\客户导出.xlsx" --eml .\examples --config .\config.local.json --state ":memory:" --output .\reports\演示结果.json

此命令仅预览，既不发送邮件，也不改变正式轮转计数。

七、预览自己的 .eml

.\inquiry-router.exe route-eml --customers "C:\路径\客户导出.xlsx" --eml "C:\路径\邮件.eml" --config .\config.local.json --output .\reports\预览结果.json

确认运行逻辑之前不要添加 --commit。

八、关于 --commit

--commit 仍然不会发送邮件，但会把决策写入 data\router_state.sqlite3，并为符合条件的普通新询盘推进计数。
同一外部直接发件人有3封不同邮件在 --commit 模式下被记录为非询盘后，会进入自动黑名单。预览模式不累计，genfollower.com内部转发中继不参与统计。
首次交接和试运行阶段请保持预览模式。

九、数据安全

便携包不包含客户 Excel、Zoho 密码或正式运行记录。Zoho密码只在使用者电脑上以Windows账户加密保存。客户 Excel 和真实邮件应由使用者保存在受控位置。

十、Windows 安全提示

当前可执行文件没有商业代码签名。其他电脑首次运行时，Windows SmartScreen 可能显示“未知发布者”；这不代表程序运行失败。
正式向多人分发前，建议由公司为可执行文件购买并配置代码签名证书。

十一、0.4.1 询盘识别规则

- Tidio通知必须含有外部客户邮箱，才按高可信询盘处理。
- MedicalExpo、RunCloud、指定内部员工、Vimeo、Google Ads、Google Analytics、OpenAI通知和中国制造网邮件固定忽略。
- 出现“View Excel”时视为钓鱼邮件并忽略。
- 只有供应商或医疗项目措辞，没有具体实验室产品诉求时进入人工复核。
- 实验室产品词支持英语、西班牙语、法语和德语。
- 动态黑名单只在正式记录模式累计；安全预览不会改变黑名单。
