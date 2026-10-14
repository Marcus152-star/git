# GenFollower 询盘路由器（影子运行版）

本项目实现方案A的Zoho影子运行阶段：读取小翼 CRM 导出的客户 Excel，以只读方式获取 Zoho 邮件，并生成建议路由结果。

0.4.1可以连接 Zoho IMAP/SMTP，并在客户端保持打开时每60秒自动检查新邮件，但**不会发送或转发邮件**。读取使用只读邮箱和 `BODY.PEEK[]`，不会把邮件标记为已读。除非命令行显式添加 `--commit`，也不会推进正式轮转计数。

## 已实现的业务顺序

1. 规则初筛是否为真实询盘；判断不足时进入人工复核。
2. 从 `Reply-To`、网站表单正文的 `From:`/`Email:` 和邮件正文提取外部客户邮箱。
3. 按完整邮箱、企业域名、公司名顺序查询小翼客户导出表。
4. 已有客户优先交给 Excel 中的“当前跟进人”。
5. CRM 无记录的新询盘先检查独家市场。
6. 未命中独家市场的新询盘进入轮转。

独家市场只作用于“真实、CRM 无记录的新询盘”，且不推进普通轮转计数：

| 国家/条件 | 销售 |
| --- | --- |
| 俄罗斯 | Chloe |
| 印度尼西亚 | Chloe |
| 以色列 | Nicole |
| 匈牙利 | Nicole |
| 乌克兰 | Chloe |
| 阿联酋且产品为 PE 吸头 | Nicole |
| 哥伦比亚 | Chloe |
| 土耳其 | Chloe |
| 斯洛文尼亚 | Chloe |
| 伊朗 | Nicole |

国家必须来自邮件中明确的 `Country:`、`国家:` 等字段才会自动触发独家市场。仅在自然语言中提及独家国家时，程序把国家置信度标为低，转入人工复核且不推进轮转计数。

普通轮转：

- 第1至第5圈：`Chloe, Nicole, Nicole, Ella, Ella`
- 第6圈起：`Chloe, Nicole, Nicole, Nicole, Ella, Ella`

## 安装

在本目录执行：

```powershell
py -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -e .
```

复制配置文件，但不要提交真实销售邮箱：

```powershell
Copy-Item .\config.example.json .\config.local.json
```

然后编辑 `config.local.json`，填写销售邮箱和当前已完成的“普通新询盘”总数。独家市场和已有客户都不包含在这个数字里。

示例：

```json
{
  "internal_domains": ["genfollower.com"],
  "internal_email_addresses": [
    "genfollower@genfollower.com",
    "marcus.chen@genfollower.com"
  ],
  "sales_email_addresses": {
    "Chloe": "填写Chloe的完整邮箱",
    "Nicole": "填写Nicole的完整邮箱",
    "Ella": "填写Ella的完整邮箱"
  },
  "initial_standard_inquiry_count": 17,
  "zoho_email_address": "marcus.chen@genfollower.com",
  "zoho_imap_host": "imappro.zoho.com",
  "zoho_imap_port": 993,
  "zoho_smtp_host": "smtppro.zoho.com",
  "zoho_smtp_port": 465,
  "zoho_folder": "INBOX"
}
```

`initial_standard_inquiry_count` 不是圈数，也不是当天的邮件数。它是程序启用前已经完成分配的“真实询盘 + CRM 无记录 + 非独家市场”累计数量。例如已经分配17封，就填 `17`；下一封从第18个位置继续。如果从全新第一圈开始，则填 `0`。

此初始值只在首次创建状态数据库时生效。数据库已存在后，如果需要校正计数，应执行：

```powershell
inquiry-router state --config .\config.local.json --set-count 17
```

请勿通过删除正式状态数据库来修改轮转起点。

## Zoho影子模式

图形客户端中的Zoho区域按以下顺序使用：

1. 填写应用专用密码，点击“保存Zoho设置”。密码使用Windows DPAPI加密到 `data\zoho_password.dpapi`，不会写入JSON配置。
2. 点击“测试收件连接”和“测试发件连接（不发信）”。SMTP测试只验证登录，不发送邮件。
3. 选择一份或多份客户Excel。
4. 可先点击“查看最近20封邮件”检查时间、发件人和主题。这个操作不做询盘判断和负责人分配，也不会改变主预览或监控起点。
5. 确认后点击“开始/继续自动监控”。首次使用会把当前最高UID设为起点，不处理此前历史邮件；已有起点时会继续原进度。
6. 客户端保持打开时每60秒自动检查新邮件并追加模拟分配结果，也可以随时手动点击“读取监控后的新邮件”。
7. “清空预览结果”只清除界面列表，不会清除监控进度或模拟轮转位置。

自动监控使用独立的模拟轮转计数并跨批次累计，不会改变正式轮转计数。Zoho下载的原始邮件保存在 `data\zoho_mail`，预览报告保存在 `reports`。这些目录都不会打包或提交到Git。

## 检查客户 Excel

图形客户端可以一次选择多份 `.xlsx`。命令行版本把多个路径依次写在 `--customers` 后：

```powershell
inquiry-router inspect-customers --customers `
  "C:\路径\客户导出1.xlsx" `
  "C:\路径\客户导出2.xlsx"
```

程序以只读方式合并客户记录。跨文件出现相同邮箱且负责人一致时仍可匹配；若负责人不同，则结果为 `ambiguous`，必须人工确认。

输出只包含记录数、邮箱数量、负责人计数和国家汇总，不输出完整客户清单。

## 测试单个客户邮箱

```powershell
inquiry-router match-customer `
  --customers "C:\路径\客户导出.xlsx" `
  --email "customer@example.com"
```

匹配结果可能是：

- `matched`：唯一负责人，可以继续路由；
- `ambiguous`：多个负责人或负责人为空，必须人工复核；
- `not_found`：没有客户记录，继续独家市场或普通轮转。

## 不等待真实询盘：运行内置演示

`examples` 目录包含10封完全虚构的邮件，覆盖普通询盘、独家市场、Newsletter、Tidio、MedicalExpo、View Excel 钓鱼、供应商骗局和德语产品询盘。

```powershell
inquiry-router route-eml `
  --customers "C:\路径\客户导出.xlsx" `
  --eml .\examples `
  --state ":memory:"
```

预期结果：

- 俄罗斯新询盘 → Chloe，不计数；
- 阿联酋 PE 吸头 → Nicole，不计数；
- 阿联酋其他产品 → 普通轮转第1个 Chloe；
- 巴西新询盘 → 普通轮转第2个 Nicole；
- Newsletter → 忽略；
- Tidio且含外部客户邮箱 → 普通轮转第3个 Nicole；
- MedicalExpo → 忽略；
- `View Excel` → 忽略；
- 只有供应商/医疗项目措辞、没有具体实验室产品 → 人工复核；
- 德语产品词加明确询价意图 → 普通轮转第4个 Ella；
- 保存的正式普通询盘计数仍为0，预览投影计数为4。

`:memory:` 表示只在内存中测试，不创建正式状态数据库。

## 发件人和询盘识别规则

- Tidio通知在含有外部客户邮箱时按高可信询盘处理；只有Tidio自身邮箱时进入人工复核。
- MedicalExpo、RunCloud、指定内部员工邮箱、Vimeo、Google Ads、Google Analytics、OpenAI通知和中国制造网固定忽略。
- `View Excel` 视为钓鱼特征并忽略。
- 供应商/医疗行业措辞但没有具体实验室产品诉求时进入人工复核。
- 产品词覆盖英语、西班牙语、法语和德语。产品词只作为证据，直接邮件仍需明确询价意图。
- 同一外部直接发件人有3封不同邮件在 `--commit` 模式下被正式记录为非询盘后，进入自动黑名单。预览模式不累计；内部转发中继不参与统计。

## 预览 `.eml` 路由

单封邮件：

```powershell
inquiry-router route-eml `
  --customers "C:\路径\客户导出.xlsx" `
  --eml "C:\路径\sample.eml" `
  --config .\config.local.json `
  --output .\reports\sample.json
```

目录内所有 `.eml`：

```powershell
inquiry-router route-eml `
  --customers "C:\路径\客户导出.xlsx" `
  --eml "C:\路径\eml样本目录" `
  --config .\config.local.json `
  --output .\reports\batch.json
```

以上命令是预览模式，不记录邮件、不推进轮转计数。

完成核对后，才可显式使用：

```powershell
inquiry-router route-eml ... --commit
```

`--commit` 只记录决定并推进符合条件的普通轮转计数，仍然不会发送邮件。

## 查看或设置轮转状态

```powershell
inquiry-router state --config .\config.local.json
inquiry-router state --config .\config.local.json --set-count 25
```

数据库默认位于 `data/router_state.sqlite3`，已被 `.gitignore` 排除。

## 测试

```powershell
python -m unittest discover -s tests -v
```

测试覆盖：

- 前5圈和第6圈后的轮转边界；
- 已有客户优先于独家市场；
- 独家市场不推进普通计数；
- 阿联酋只有 PE 吸头命中 Nicole；
- WordPress 正文真实邮箱提取；
- 重复邮件不重复推进计数。

## 构建 Windows 便携包

便携包包含可双击使用的图形客户端 `GenFollower-Inquiry-Router-GUI.exe`，同时保留命令行版本 `inquiry-router.exe`。接手人的电脑不需要预装 Python。开发电脑首次构建时执行：

```powershell
.\.venv\Scripts\python.exe -m pip install -e ".[packaging]"
.\tools\build_portable.ps1
```

构建结果位于 `release\GenFollower-Inquiry-Router-0.4.1-windows-x64.zip`。包内只有可执行文件、空白配置模板、虚构测试邮件和中文说明，不包含客户 Excel、邮箱密码或正式状态数据库。

## 当前限制

- 询盘分类目前是保守的规则初筛，不确定的邮件进入人工复核；尚未连接 AI 模型。
- 只有明确国家字段才能自动触发独家市场。缺少国家时不会根据域名武断推断。
- 当前只读连接 Zoho，不发送邮件，也不修改小翼 CRM。
- 自动检查仅在客户端保持打开时运行；关闭客户端后不会作为Windows后台服务继续运行。
- 需要真实 `.eml` 样本校准不同来源的转发格式和询盘语言。
- 需要确认 `当前跟进人` 与实际销售姓名、邮箱之间的完整映射。

