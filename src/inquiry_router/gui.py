from __future__ import annotations

import json
import os
import sys
import tkinter as tk
from datetime import datetime
from email import policy
from email.parser import BytesParser
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

from .classifier import assess_inquiry
from .config import AppConfig, load_config
from .credential_store import WindowsCredentialStore
from .customers import CustomerIndex
from .email_parser import parse_eml
from .router import make_decision
from .state import StateStore
from .zoho_mail import ZohoMailClient


ROUTE_LABELS = {
    "existing_customer": "CRM老客户",
    "exclusive_market": "独家市场",
    "standard_round_robin": "普通轮转",
    "manual_review": "人工复核",
    "ignored": "忽略",
    "duplicate": "重复邮件",
}

INQUIRY_LABELS = {
    "true": "真实询盘",
    "false": "非询盘",
    "review": "待复核",
}

MATCH_LABELS = {
    "matched": "已匹配",
    "ambiguous": "需要人工确认",
    "not_found": "未找到客户记录",
}


def format_customer_match(match) -> str:
    countries = "、".join(match.countries) or "未填写"
    companies = "、".join(match.company_names) or "未填写"
    owner = match.owner or "未确定"
    return "\n".join(
        (
            f"匹配状态：{MATCH_LABELS.get(match.status, match.status)}",
            f"客户所属国家：{countries}",
            f"所属公司：{companies}",
            f"负责人：{owner}",
        )
    )


def format_customer_summary(summary: dict) -> str:
    lines = [
        f"导入客户表：{summary.get('source_file_count', 0)}份",
        f"客户记录总数：{summary['records']}条",
        f"有当前跟进人的客户记录：{summary['records_with_current_owner']}条",
        f"有国家信息的客户记录：{summary['records_with_country']}条",
        f"有邮箱的客户记录：{summary['records_with_email']}条",
        f"没有邮箱的客户记录：{summary['records_without_email']}条",
        f"唯一邮箱数量：{summary['unique_emails']}个",
        f"唯一企业域名数量：{summary['unique_business_domains']}个",
        f"重复邮箱记录：{summary['duplicate_email_values']}条",
        "",
        "各负责人客户记录：",
    ]
    lines.extend(f"  {owner}：{count}条" for owner, count in summary["owner_counts"].items())
    lines.extend(("", "主要客户国家："))
    lines.extend(f"  {country}：{count}条" for country, count in summary["top_countries"].items())
    return "\n".join(lines)


def application_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path.cwd()


def email_overview(path: Path) -> dict[str, str]:
    message = BytesParser(policy=policy.default).parsebytes(path.read_bytes())
    return {
        "date": str(message.get("Date", "")),
        "from": str(message.get("From", "")),
        "subject": str(message.get("Subject", "")),
    }


class InquiryRouterApp:
    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        self.app_dir = application_dir()
        self.config_path = self.app_dir / "config.local.json"
        self.state_path = self.app_dir / "data" / "router_state.sqlite3"
        self.zoho_mail_dir = self.app_dir / "data" / "zoho_mail"
        self.credential_store = WindowsCredentialStore(self.app_dir / "data" / "zoho_password.dpapi")
        self.reports_dir = self.app_dir / "reports"
        self.reports_dir.mkdir(parents=True, exist_ok=True)

        self.customers_var = tk.StringVar()
        self.customer_paths: list[Path] = []
        self.eml_var = tk.StringVar()
        self.test_email_var = tk.StringVar()
        self.chloe_var = tk.StringVar()
        self.nicole_var = tk.StringVar()
        self.ella_var = tk.StringVar()
        self.initial_count_var = tk.StringVar(value="0")
        self.current_count_var = tk.StringVar()
        self.current_count_display = tk.StringVar(value="尚未读取")
        self.zoho_email_var = tk.StringVar(value="marcus.chen@genfollower.com")
        self.zoho_password_var = tk.StringVar()
        self.zoho_imap_host_var = tk.StringVar(value="imappro.zoho.com")
        self.zoho_imap_port_var = tk.StringVar(value="993")
        self.zoho_smtp_host_var = tk.StringVar(value="smtppro.zoho.com")
        self.zoho_smtp_port_var = tk.StringVar(value="465")
        self.zoho_folder_var = tk.StringVar(value="INBOX")
        self.zoho_password_status_var = tk.StringVar(value="应用专用密码：未保存")
        self.zoho_checkpoint_var = tk.StringVar(value="监控起点：尚未设置")
        self.zoho_monitor_status_var = tk.StringVar(value="自动监控：未启动")
        self.auto_monitoring = False
        self.auto_monitor_after_id: str | None = None
        self.auto_monitor_interval_ms = 60_000
        self.status_var = tk.StringVar(value="就绪：当前客户端只做预览，不发送邮件。")

        self._build_window()
        self._load_config(show_message=False)
        self._show_current_count(create=False)

    def _build_window(self) -> None:
        self.root.title("GenFollower 询盘路由器（影子运行版）")
        self.root.geometry("1240x900")
        self.root.minsize(1020, 760)

        outer = ttk.Frame(self.root, padding=12)
        outer.grid(row=0, column=0, sticky="nsew")
        self.root.rowconfigure(0, weight=1)
        self.root.columnconfigure(0, weight=1)
        outer.columnconfigure(0, weight=1)
        outer.rowconfigure(5, weight=1)

        notice = ttk.Label(
            outer,
            text="Zoho影子模式：可以只读连接和下载邮件；不会发送邮件、不会标记已读、不会推进正式轮转计数。",
            foreground="#9A3412",
        )
        notice.grid(row=0, column=0, sticky="w", pady=(0, 8))

        settings = ttk.LabelFrame(outer, text="1. 销售邮箱与轮转计数", padding=10)
        settings.grid(row=1, column=0, sticky="ew", pady=(0, 8))
        for column in (1, 3, 5):
            settings.columnconfigure(column, weight=1)

        ttk.Label(settings, text="Chloe 邮箱").grid(row=0, column=0, sticky="w")
        ttk.Entry(settings, textvariable=self.chloe_var).grid(row=0, column=1, sticky="ew", padx=(5, 12))
        ttk.Label(settings, text="Nicole 邮箱").grid(row=0, column=2, sticky="w")
        ttk.Entry(settings, textvariable=self.nicole_var).grid(row=0, column=3, sticky="ew", padx=(5, 12))
        ttk.Label(settings, text="Ella 邮箱").grid(row=0, column=4, sticky="w")
        ttk.Entry(settings, textvariable=self.ella_var).grid(row=0, column=5, sticky="ew", padx=(5, 0))

        ttk.Label(settings, text="初始普通询盘累计数").grid(row=1, column=0, sticky="w", pady=(8, 0))
        ttk.Entry(settings, textvariable=self.initial_count_var, width=12).grid(
            row=1, column=1, sticky="w", padx=(5, 12), pady=(8, 0)
        )
        ttk.Button(settings, text="保存配置", command=self._save_config).grid(row=1, column=2, pady=(8, 0))
        ttk.Button(settings, text="用记事本打开配置", command=self._open_config).grid(
            row=1, column=3, sticky="w", padx=(5, 0), pady=(8, 0)
        )
        ttk.Label(settings, text="当前正式计数：").grid(row=2, column=0, sticky="w", pady=(8, 0))
        ttk.Label(settings, textvariable=self.current_count_display).grid(
            row=2, column=1, sticky="w", padx=(5, 12), pady=(8, 0)
        )
        ttk.Entry(settings, textvariable=self.current_count_var, width=12).grid(
            row=2, column=2, sticky="w", pady=(8, 0)
        )
        ttk.Button(settings, text="设置正式计数", command=self._set_current_count).grid(
            row=2, column=3, sticky="w", padx=(5, 0), pady=(8, 0)
        )
        ttk.Button(settings, text="重新读取", command=lambda: self._show_current_count(create=False)).grid(
            row=2, column=4, sticky="w", pady=(8, 0)
        )

        zoho = ttk.LabelFrame(outer, text="2. Zoho 邮箱（只读影子模式）", padding=10)
        zoho.grid(row=2, column=0, sticky="ew", pady=(0, 8))
        for column in (1, 3, 5):
            zoho.columnconfigure(column, weight=1)

        ttk.Label(zoho, text="邮箱账号").grid(row=0, column=0, sticky="w")
        ttk.Entry(zoho, textvariable=self.zoho_email_var).grid(row=0, column=1, sticky="ew", padx=(5, 12))
        ttk.Label(zoho, text="应用专用密码").grid(row=0, column=2, sticky="w")
        ttk.Entry(zoho, textvariable=self.zoho_password_var, show="●").grid(
            row=0, column=3, sticky="ew", padx=(5, 12)
        )
        ttk.Label(zoho, textvariable=self.zoho_password_status_var).grid(row=0, column=4, columnspan=2, sticky="w")

        ttk.Label(zoho, text="IMAP服务器").grid(row=1, column=0, sticky="w", pady=(8, 0))
        ttk.Entry(zoho, textvariable=self.zoho_imap_host_var).grid(
            row=1, column=1, sticky="ew", padx=(5, 12), pady=(8, 0)
        )
        ttk.Label(zoho, text="端口").grid(row=1, column=2, sticky="w", pady=(8, 0))
        ttk.Entry(zoho, textvariable=self.zoho_imap_port_var, width=8).grid(
            row=1, column=3, sticky="w", padx=(5, 12), pady=(8, 0)
        )
        ttk.Label(zoho, text="文件夹").grid(row=1, column=4, sticky="w", pady=(8, 0))
        ttk.Entry(zoho, textvariable=self.zoho_folder_var, width=12).grid(
            row=1, column=5, sticky="w", padx=(5, 0), pady=(8, 0)
        )

        ttk.Label(zoho, text="SMTP服务器").grid(row=2, column=0, sticky="w", pady=(8, 0))
        ttk.Entry(zoho, textvariable=self.zoho_smtp_host_var).grid(
            row=2, column=1, sticky="ew", padx=(5, 12), pady=(8, 0)
        )
        ttk.Label(zoho, text="端口").grid(row=2, column=2, sticky="w", pady=(8, 0))
        ttk.Entry(zoho, textvariable=self.zoho_smtp_port_var, width=8).grid(
            row=2, column=3, sticky="w", padx=(5, 12), pady=(8, 0)
        )
        ttk.Button(zoho, text="保存Zoho设置", command=self._save_zoho_config).grid(
            row=2, column=4, sticky="w", pady=(8, 0)
        )
        ttk.Button(zoho, text="测试收件连接", command=self._test_zoho_imap).grid(
            row=2, column=5, sticky="w", pady=(8, 0)
        )

        ttk.Label(zoho, textvariable=self.zoho_checkpoint_var).grid(
            row=3, column=0, columnspan=2, sticky="w", pady=(8, 0)
        )
        ttk.Button(zoho, text="测试发件连接（不发信）", command=self._test_zoho_smtp).grid(
            row=3, column=2, sticky="w", pady=(8, 0)
        )
        ttk.Button(zoho, text="查看最近20封邮件", command=self._read_recent_zoho).grid(
            row=3, column=3, sticky="w", pady=(8, 0)
        )
        ttk.Button(zoho, text="开始/继续自动监控", command=self._start_zoho_monitoring).grid(
            row=3, column=4, sticky="w", pady=(8, 0)
        )
        ttk.Button(zoho, text="读取监控后的新邮件", command=self._read_new_zoho).grid(
            row=3, column=5, sticky="w", pady=(8, 0)
        )
        ttk.Label(zoho, textvariable=self.zoho_monitor_status_var).grid(
            row=4, column=0, columnspan=2, sticky="w", pady=(8, 0)
        )
        ttk.Button(zoho, text="停止自动监控", command=self._stop_zoho_monitoring).grid(
            row=4, column=2, sticky="w", pady=(8, 0)
        )

        sources = ttk.LabelFrame(outer, text="3. 选择数据", padding=10)
        sources.grid(row=3, column=0, sticky="ew", pady=(0, 8))
        sources.columnconfigure(1, weight=1)
        ttk.Label(sources, text="客户 Excel（可多选）").grid(row=0, column=0, sticky="w")
        ttk.Entry(sources, textvariable=self.customers_var).grid(row=0, column=1, sticky="ew", padx=8)
        ttk.Button(sources, text="选择 Excel（可多选）", command=self._browse_customers).grid(row=0, column=2)
        ttk.Button(sources, text="检查客户表", command=self._inspect_customers).grid(row=0, column=3, padx=(8, 0))

        ttk.Label(sources, text="邮件 .eml/文件夹").grid(row=1, column=0, sticky="w", pady=(8, 0))
        ttk.Entry(sources, textvariable=self.eml_var).grid(row=1, column=1, sticky="ew", padx=8, pady=(8, 0))
        ttk.Button(sources, text="选择单封邮件", command=self._browse_eml_file).grid(row=1, column=2, pady=(8, 0))
        ttk.Button(sources, text="选择邮件文件夹", command=self._browse_eml_folder).grid(
            row=1, column=3, padx=(8, 0), pady=(8, 0)
        )

        actions = ttk.LabelFrame(outer, text="4. 检查与预览", padding=10)
        actions.grid(row=4, column=0, sticky="ew", pady=(0, 8))
        actions.columnconfigure(1, weight=1)
        ttk.Label(actions, text="测试客户邮箱").grid(row=0, column=0, sticky="w")
        ttk.Entry(actions, textvariable=self.test_email_var).grid(row=0, column=1, sticky="ew", padx=8)
        ttk.Button(actions, text="查询负责人", command=self._match_customer).grid(row=0, column=2)
        ttk.Button(actions, text="预览分配", command=self._preview_routes).grid(row=0, column=3, padx=(8, 0))
        ttk.Button(actions, text="打开结果文件夹", command=self._open_reports).grid(row=0, column=4, padx=(8, 0))
        ttk.Button(actions, text="清空预览结果", command=self._clear_preview).grid(row=0, column=5, padx=(8, 0))

        results = ttk.LabelFrame(outer, text="5. 预览结果", padding=8)
        results.grid(row=5, column=0, sticky="nsew")
        results.rowconfigure(0, weight=1)
        results.columnconfigure(0, weight=1)
        columns = ("file", "inquiry", "email", "country", "match", "route", "salesperson", "number")
        self.tree = ttk.Treeview(results, columns=columns, show="headings")
        headings = {
            "file": "邮件文件",
            "inquiry": "询盘判断",
            "email": "客户邮箱",
            "country": "国家",
            "match": "CRM匹配",
            "route": "路由类型",
            "salesperson": "负责人",
            "number": "普通序号",
        }
        widths = {"file": 180, "inquiry": 90, "email": 200, "country": 110, "match": 100, "route": 100, "salesperson": 90, "number": 80}
        for column in columns:
            self.tree.heading(column, text=headings[column])
            self.tree.column(column, width=widths[column], minwidth=60, stretch=column in {"file", "email"})
        yscroll = ttk.Scrollbar(results, orient="vertical", command=self.tree.yview)
        xscroll = ttk.Scrollbar(results, orient="horizontal", command=self.tree.xview)
        self.tree.configure(yscrollcommand=yscroll.set, xscrollcommand=xscroll.set)
        self.tree.grid(row=0, column=0, sticky="nsew")
        yscroll.grid(row=0, column=1, sticky="ns")
        xscroll.grid(row=1, column=0, sticky="ew")

        ttk.Label(outer, textvariable=self.status_var, relief="sunken", anchor="w", padding=5).grid(
            row=6, column=0, sticky="ew", pady=(8, 0)
        )

    def _read_raw_config(self) -> dict:
        if self.config_path.exists():
            return json.loads(self.config_path.read_text(encoding="utf-8"))
        return {
            "internal_domains": ["genfollower.com"],
            "internal_email_addresses": [
                "genfollower@genfollower.com",
                "marcus.chen@genfollower.com",
            ],
            "sales_email_addresses": {"Chloe": "", "Nicole": "", "Ella": ""},
            "initial_standard_inquiry_count": 0,
            "zoho_email_address": "marcus.chen@genfollower.com",
            "zoho_imap_host": "imappro.zoho.com",
            "zoho_imap_port": 993,
            "zoho_smtp_host": "smtppro.zoho.com",
            "zoho_smtp_port": 465,
            "zoho_folder": "INBOX",
        }

    def _load_config(self, show_message: bool = True) -> None:
        try:
            raw = self._read_raw_config()
            sales = raw.get("sales_email_addresses", {})
            self.chloe_var.set(str(sales.get("Chloe", "")))
            self.nicole_var.set(str(sales.get("Nicole", "")))
            self.ella_var.set(str(sales.get("Ella", "")))
            self.initial_count_var.set(str(raw.get("initial_standard_inquiry_count", 0)))
            self.zoho_email_var.set(str(raw.get("zoho_email_address", "marcus.chen@genfollower.com")))
            self.zoho_imap_host_var.set(str(raw.get("zoho_imap_host", "imappro.zoho.com")))
            self.zoho_imap_port_var.set(str(raw.get("zoho_imap_port", 993)))
            self.zoho_smtp_host_var.set(str(raw.get("zoho_smtp_host", "smtppro.zoho.com")))
            self.zoho_smtp_port_var.set(str(raw.get("zoho_smtp_port", 465)))
            self.zoho_folder_var.set(str(raw.get("zoho_folder", "INBOX")))
            self.zoho_password_status_var.set(
                "应用专用密码：已安全保存" if self.credential_store.exists() else "应用专用密码：未保存"
            )
            self._show_zoho_checkpoint()
            self.status_var.set(f"已读取配置：{self.config_path}")
            if show_message:
                messagebox.showinfo("配置", "配置已重新读取。")
        except Exception as exc:
            self._show_error("读取配置失败", exc)

    def _save_config(self) -> None:
        try:
            emails = {
                "Chloe": self.chloe_var.get().strip().lower(),
                "Nicole": self.nicole_var.get().strip().lower(),
                "Ella": self.ella_var.get().strip().lower(),
            }
            invalid = [name for name, email in emails.items() if "@" not in email]
            if invalid:
                raise ValueError(f"请填写有效邮箱：{', '.join(invalid)}")
            count = int(self.initial_count_var.get().strip())
            if count < 0:
                raise ValueError("初始普通询盘累计数不能小于0")
            raw = self._read_raw_config()
            raw["sales_email_addresses"] = emails
            raw["initial_standard_inquiry_count"] = count
            temporary = self.config_path.with_suffix(".json.tmp")
            temporary.write_text(json.dumps(raw, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            temporary.replace(self.config_path)
            self.status_var.set(f"配置已保存：{self.config_path}")
            messagebox.showinfo("保存成功", "销售邮箱和初始轮转计数已保存。")
        except Exception as exc:
            self._show_error("保存配置失败", exc)

    def _open_config(self) -> None:
        try:
            if not self.config_path.exists():
                raise FileNotFoundError("请先点击“保存配置”创建 config.local.json")
            os.startfile(self.config_path)
        except Exception as exc:
            self._show_error("无法打开配置", exc)

    def _zoho_values(self) -> dict:
        email_address = self.zoho_email_var.get().strip().lower()
        if "@" not in email_address:
            raise ValueError("请填写有效的 Zoho 邮箱账号")
        imap_host = self.zoho_imap_host_var.get().strip()
        smtp_host = self.zoho_smtp_host_var.get().strip()
        folder = self.zoho_folder_var.get().strip() or "INBOX"
        if not imap_host or not smtp_host:
            raise ValueError("IMAP和SMTP服务器不能为空")
        imap_port = int(self.zoho_imap_port_var.get().strip())
        smtp_port = int(self.zoho_smtp_port_var.get().strip())
        if not (1 <= imap_port <= 65535 and 1 <= smtp_port <= 65535):
            raise ValueError("邮箱服务器端口必须在1至65535之间")
        return {
            "zoho_email_address": email_address,
            "zoho_imap_host": imap_host,
            "zoho_imap_port": imap_port,
            "zoho_smtp_host": smtp_host,
            "zoho_smtp_port": smtp_port,
            "zoho_folder": folder,
        }

    def _save_zoho_config(self) -> None:
        try:
            values = self._zoho_values()
            password = self.zoho_password_var.get()
            raw = self._read_raw_config()
            raw.update(values)
            temporary = self.config_path.with_suffix(".json.tmp")
            temporary.write_text(json.dumps(raw, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            temporary.replace(self.config_path)
            if password:
                self.credential_store.save(password)
                self.zoho_password_var.set("")
            if not self.credential_store.exists():
                raise ValueError("请填写应用专用密码后再次保存")
            self.zoho_password_status_var.set("应用专用密码：已安全保存")
            self.status_var.set("Zoho设置已保存；密码已使用Windows账户加密。")
            messagebox.showinfo(
                "Zoho设置已保存",
                "服务器设置已保存。\n应用专用密码已使用当前Windows账户加密，不会写入配置文件。",
            )
        except Exception as exc:
            self._show_error("保存Zoho设置失败", exc)

    def _zoho_client(self) -> ZohoMailClient:
        values = self._zoho_values()
        password = self.zoho_password_var.get() or self.credential_store.load()
        return ZohoMailClient(
            email_address=values["zoho_email_address"],
            password=password,
            imap_host=values["zoho_imap_host"],
            imap_port=values["zoho_imap_port"],
            smtp_host=values["zoho_smtp_host"],
            smtp_port=values["zoho_smtp_port"],
            folder=values["zoho_folder"],
        )

    def _show_zoho_checkpoint(self) -> None:
        try:
            values = self._zoho_values()
            if not self.state_path.exists():
                self.zoho_checkpoint_var.set("监控起点：尚未设置")
                return
            with StateStore(self.state_path) as state:
                checkpoint = state.get_mailbox_checkpoint(
                    values["zoho_email_address"], values["zoho_folder"]
                )
            if checkpoint:
                self.zoho_checkpoint_var.set(f"监控起点：UID {checkpoint[1]}")
            else:
                self.zoho_checkpoint_var.set("监控起点：尚未设置")
        except Exception:
            self.zoho_checkpoint_var.set("监控起点：无法读取")

    def _test_zoho_imap(self) -> None:
        try:
            snapshot = self._zoho_client().test_imap()
            self.status_var.set(f"Zoho收件连接成功；当前最高邮件UID：{snapshot.highest_uid}")
            messagebox.showinfo(
                "收件连接成功",
                f"已只读连接Zoho邮箱。\n当前最高邮件UID：{snapshot.highest_uid}\n没有读取或修改邮件。",
            )
        except Exception as exc:
            self._show_error("Zoho收件连接失败", exc)

    def _test_zoho_smtp(self) -> None:
        try:
            self._zoho_client().test_smtp()
            self.status_var.set("Zoho发件连接认证成功；没有发送测试邮件。")
            messagebox.showinfo("发件连接成功", "SMTP身份验证成功。此次测试没有发送任何邮件。")
        except Exception as exc:
            self._show_error("Zoho发件连接失败", exc)

    def _start_zoho_monitoring(self) -> None:
        try:
            self._customer_files()
            values = self._zoho_values()
            snapshot = self._zoho_client().test_imap()
            config = load_config(self.config_path if self.config_path.exists() else None)
            with StateStore(self.state_path, config.initial_standard_inquiry_count) as state:
                checkpoint = state.get_mailbox_checkpoint(
                    values["zoho_email_address"], values["zoho_folder"]
                )
                created_checkpoint = checkpoint is None
                if checkpoint and checkpoint[0] != snapshot.uid_validity:
                    raise RuntimeError("邮箱UIDVALIDITY已变化，无法安全继续原监控起点")
                if not checkpoint:
                    state.set_mailbox_checkpoint(
                        values["zoho_email_address"],
                        values["zoho_folder"],
                        snapshot.uid_validity,
                        snapshot.highest_uid,
                    )
                    checkpoint = (snapshot.uid_validity, snapshot.highest_uid)
                if state.get_mailbox_shadow_count(
                    values["zoho_email_address"], values["zoho_folder"]
                ) is None:
                    state.set_mailbox_shadow_count(
                        values["zoho_email_address"],
                        values["zoho_folder"],
                        state.get_standard_count(),
                    )
            self._show_zoho_checkpoint()
            self.auto_monitoring = True
            self._schedule_auto_monitor(1_000)
            self.zoho_monitor_status_var.set("自动监控：运行中（每60秒检查一次）")
            self.status_var.set(f"Zoho自动监控已启动；当前起点UID：{checkpoint[1]}")
            start_text = (
                "已把当前最新邮件设为起点；此前历史邮件不会参与模拟分配。"
                if created_checkpoint
                else "已保留原监控进度并继续检查新邮件。"
            )
            messagebox.showinfo(
                "自动监控已启动",
                f"{start_text}\n当前起点UID：{checkpoint[1]}\n"
                "客户端保持打开时，每60秒自动检查一次。\n"
                "只做模拟分配，不发送邮件、不推进正式计数。",
            )
        except Exception as exc:
            self._show_error("启动Zoho自动监控失败", exc)

    def _schedule_auto_monitor(self, delay_ms: int | None = None) -> None:
        if self.auto_monitor_after_id is not None:
            self.root.after_cancel(self.auto_monitor_after_id)
        delay = self.auto_monitor_interval_ms if delay_ms is None else delay_ms
        self.auto_monitor_after_id = self.root.after(delay, self._auto_monitor_tick)

    def _auto_monitor_tick(self) -> None:
        self.auto_monitor_after_id = None
        if not self.auto_monitoring:
            return
        try:
            count = self._fetch_new_zoho(show_dialog=False)
            checked_at = datetime.now().strftime("%H:%M:%S")
            if count:
                self.zoho_monitor_status_var.set(
                    f"自动监控：运行中；{checked_at} 新增 {count} 封预览"
                )
            else:
                self.zoho_monitor_status_var.set(
                    f"自动监控：运行中；{checked_at} 未发现新邮件"
                )
        except Exception as exc:
            self.zoho_monitor_status_var.set(f"自动监控：检查失败（{exc}）")
            self.status_var.set(f"Zoho自动检查失败：{exc}")
        finally:
            if self.auto_monitoring:
                self._schedule_auto_monitor()

    def _stop_zoho_monitoring(self) -> None:
        self.auto_monitoring = False
        if self.auto_monitor_after_id is not None:
            self.root.after_cancel(self.auto_monitor_after_id)
            self.auto_monitor_after_id = None
        self.zoho_monitor_status_var.set("自动监控：已停止")
        self.status_var.set("Zoho自动监控已停止；已保存的邮件监控进度不会丢失。")

    def _show_current_count(self, create: bool) -> None:
        try:
            if not self.state_path.exists() and not create:
                self.current_count_display.set("尚未创建状态数据库")
                return
            config = load_config(self.config_path if self.config_path.exists() else None)
            with StateStore(self.state_path, config.initial_standard_inquiry_count) as state:
                count = state.get_standard_count()
            self.current_count_display.set(str(count))
            self.current_count_var.set(str(count))
        except Exception as exc:
            self._show_error("读取轮转计数失败", exc)

    def _set_current_count(self) -> None:
        try:
            count = int(self.current_count_var.get().strip())
            if count < 0:
                raise ValueError("正式轮转计数不能小于0")
            config = load_config(self.config_path if self.config_path.exists() else None)
            with StateStore(self.state_path, config.initial_standard_inquiry_count) as state:
                state.set_standard_count(count)
            self.current_count_display.set(str(count))
            self.status_var.set(f"正式轮转计数已设置为 {count}")
            messagebox.showinfo("设置成功", f"当前正式轮转计数：{count}")
        except Exception as exc:
            self._show_error("设置轮转计数失败", exc)

    def _browse_customers(self) -> None:
        paths = filedialog.askopenfilenames(
            title="选择一个或多个小翼 CRM 客户 Excel",
            filetypes=[("Excel 文件", "*.xlsx")],
        )
        if paths:
            self.customer_paths = [Path(path) for path in paths]
            self.customers_var.set("; ".join(str(path) for path in self.customer_paths))

    def _browse_eml_file(self) -> None:
        path = filedialog.askopenfilename(title="选择邮件", filetypes=[("EML 邮件", "*.eml")])
        if path:
            self.eml_var.set(path)

    def _browse_eml_folder(self) -> None:
        path = filedialog.askdirectory(title="选择包含 .eml 的文件夹")
        if path:
            self.eml_var.set(path)

    def _customer_files(self) -> list[Path]:
        paths = [Path(value.strip().strip('"')) for value in self.customers_var.get().split(";") if value.strip()]
        if not paths:
            raise FileNotFoundError("请先选择至少一份客户 Excel")
        missing = [path.name or str(path) for path in paths if not path.is_file()]
        if missing:
            raise FileNotFoundError(f"找不到客户 Excel：{'、'.join(missing)}")
        return paths

    def _customer_index(self) -> CustomerIndex:
        return CustomerIndex.from_xlsx_files(self._customer_files())

    def _inspect_customers(self) -> None:
        try:
            summary = self._customer_index().summary()
            self.status_var.set(
                f"客户表检查完成：{summary['source_file_count']} 份，合计 {summary['records']} 条客户记录。"
            )
            self._show_text_dialog("客户表检查结果", format_customer_summary(summary))
        except Exception as exc:
            self._show_error("检查客户表失败", exc)

    def _match_customer(self) -> None:
        try:
            email = self.test_email_var.get().strip().lower()
            if "@" not in email:
                raise ValueError("请输入需要测试的完整客户邮箱")
            match = self._customer_index().match([email], "")
            self.status_var.set(f"邮箱查询完成：{email} → {match.owner or match.status}")
            messagebox.showinfo("邮箱查询结果", format_customer_match(match))
        except Exception as exc:
            self._show_error("查询客户失败", exc)

    def _eml_paths(self) -> list[Path]:
        path = Path(self.eml_var.get().strip())
        if path.is_file() and path.suffix.lower() == ".eml":
            return [path]
        if path.is_dir():
            paths = sorted(path.glob("*.eml"))
            if paths:
                return paths
            raise ValueError("所选文件夹中没有 .eml 文件")
        raise FileNotFoundError("请先选择有效的 .eml 文件或文件夹")

    def _preview_routes(self) -> None:
        try:
            paths = self._eml_paths()
            decisions, output, _ = self._preview_paths(paths)
            messagebox.showinfo("预览完成", f"共处理 {len(decisions)} 封邮件。\n\n正式计数未改变。\n结果文件：{output}")
        except Exception as exc:
            self._show_error("预览分配失败", exc)

    def _preview_paths(
        self,
        paths: list[Path],
        append: bool = False,
        starting_preview_count: int | None = None,
    ) -> tuple[list[dict], Path, int]:
        config = load_config(self.config_path if self.config_path.exists() else None)
        index = self._customer_index()
        if self.state_path.exists():
            with StateStore(self.state_path, config.initial_standard_inquiry_count) as state:
                stored_count = state.get_standard_count()
                blacklisted_senders = state.get_blacklisted_senders()
        else:
            stored_count = config.initial_standard_inquiry_count
            blacklisted_senders = set()
        preview_count = stored_count if starting_preview_count is None else starting_preview_count
        decisions: list[dict] = []
        for path in paths:
            parsed = parse_eml(path, config)
            assessment = assess_inquiry(parsed, blacklisted_senders)
            match = index.match(parsed.customer_email_candidates, parsed.company_name)
            decision = make_decision(parsed, assessment, match, preview_count, config)
            if decision.advances_standard_counter:
                preview_count += 1
            result = decision.to_dict()
            result.update(
                {
                    "source_path": parsed.source_path,
                    "subject": parsed.subject,
                    "customer_name": parsed.customer_name,
                    "company_name": parsed.company_name,
                }
            )
            decisions.append(result)

        payload = {
            "mode": "preview",
            "email_sending_enabled": False,
            "stored_standard_inquiry_count_before_run": stored_count,
            "stored_standard_inquiry_count_after_run": stored_count,
            "projected_standard_inquiry_count_after_run": preview_count,
            "decisions": decisions,
        }
        timestamp = datetime.now().strftime("%Y%m%d-%H%M%S-%f")
        output = self.reports_dir / f"preview-{timestamp}.json"
        output.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        self._fill_tree(decisions, append=append)
        self.status_var.set(
            f"预览完成：{len(decisions)} 封邮件；正式计数未改变；结果已保存到 {output.name}"
        )
        return decisions, output, preview_count

    def _read_recent_zoho(self) -> None:
        try:
            folder = self.zoho_mail_dir / f"recent-{datetime.now().strftime('%Y%m%d-%H%M%S')}"
            _, downloaded = self._zoho_client().download_recent(folder, limit=20)
            if not downloaded:
                messagebox.showinfo("读取完成", "Zoho收件箱目前没有邮件。")
                return
            self._show_recent_email_dialog(downloaded)
            self.status_var.set(
                f"已读取最近 {len(downloaded)} 封邮件供核对；未进行询盘判断或负责人分配。"
            )
        except Exception as exc:
            self._show_error("读取Zoho最近邮件失败", exc)

    def _read_new_zoho(self) -> None:
        try:
            self._fetch_new_zoho(show_dialog=True)
        except Exception as exc:
            self._show_error("读取Zoho新邮件失败", exc)

    def _fetch_new_zoho(self, show_dialog: bool) -> int:
        self._customer_files()
        values = self._zoho_values()
        config = load_config(self.config_path if self.config_path.exists() else None)
        with StateStore(self.state_path, config.initial_standard_inquiry_count) as state:
            formal_count = state.get_standard_count()
            checkpoint = state.get_mailbox_checkpoint(
                values["zoho_email_address"], values["zoho_folder"]
            )
            shadow_count = state.get_mailbox_shadow_count(
                values["zoho_email_address"], values["zoho_folder"]
            )
        if not checkpoint:
            raise RuntimeError("请先点击“开始/继续自动监控”设置安全起点")
        if shadow_count is None:
            shadow_count = formal_count

        folder = self.zoho_mail_dir / f"new-{datetime.now().strftime('%Y%m%d-%H%M%S-%f')}"
        snapshot, downloaded = self._zoho_client().download_after(
            folder,
            last_uid=checkpoint[1],
            expected_uid_validity=checkpoint[0],
        )
        if not downloaded:
            self.status_var.set("检查完成：监控起点之后没有新邮件。")
            if show_dialog:
                messagebox.showinfo("没有新邮件", "监控起点之后没有发现新邮件。")
            return 0

        paths = [item.path for item in downloaded]
        decisions, output, projected_shadow_count = self._preview_paths(
            paths,
            append=True,
            starting_preview_count=shadow_count,
        )
        with StateStore(self.state_path, config.initial_standard_inquiry_count) as state:
            state.set_mailbox_checkpoint(
                values["zoho_email_address"],
                values["zoho_folder"],
                snapshot.uid_validity,
                snapshot.highest_uid,
            )
            state.set_mailbox_shadow_count(
                values["zoho_email_address"],
                values["zoho_folder"],
                projected_shadow_count,
            )
        self._show_zoho_checkpoint()
        if show_dialog:
            messagebox.showinfo(
                "Zoho新邮件模拟分配完成",
                f"新增 {len(decisions)} 封邮件，结果已追加到当前列表。\n"
                "邮件未标记为已读，正式计数未改变。\n"
                f"结果文件：{output}",
            )
        return len(decisions)

    def _fill_tree(self, decisions: list[dict], append: bool = False) -> None:
        if not append:
            self._clear_preview(update_status=False)
        for decision in decisions:
            emails = ", ".join(decision.get("extracted_customer_emails", []))
            number = decision.get("standard_inquiry_number")
            self.tree.insert(
                "",
                "end",
                values=(
                    Path(decision.get("source_path", "")).name,
                    INQUIRY_LABELS.get(decision.get("inquiry_status", ""), decision.get("inquiry_status", "")),
                    emails,
                    decision.get("country", ""),
                    decision.get("customer_match_status", ""),
                    ROUTE_LABELS.get(decision.get("route_type", ""), decision.get("route_type", "")),
                    decision.get("salesperson", ""),
                    "" if number is None else number,
                ),
            )

    def _clear_preview(self, update_status: bool = True) -> None:
        for item in self.tree.get_children():
            self.tree.delete(item)
        if update_status:
            self.status_var.set("预览结果已清空；邮件监控进度和正式轮转计数未改变。")

    def _show_recent_email_dialog(self, downloaded) -> None:
        window = tk.Toplevel(self.root)
        window.title("Zoho最近20封邮件（仅核对，不参与分配）")
        window.geometry("980x520")
        window.minsize(760, 360)
        window.transient(self.root)

        frame = ttk.Frame(window, padding=12)
        frame.pack(fill="both", expand=True)
        ttk.Label(
            frame,
            text="以下邮件仅用于确认Zoho读取范围，不做询盘判断、不分配负责人、不改变监控起点。",
            foreground="#1D4ED8",
        ).pack(anchor="w", pady=(0, 8))

        columns = ("uid", "date", "from", "subject")
        tree = ttk.Treeview(frame, columns=columns, show="headings")
        headings = {"uid": "UID", "date": "邮件时间", "from": "发件人", "subject": "主题"}
        widths = {"uid": 80, "date": 210, "from": 270, "subject": 380}
        for column in columns:
            tree.heading(column, text=headings[column])
            tree.column(column, width=widths[column], minwidth=60, stretch=column in {"from", "subject"})
        scrollbar = ttk.Scrollbar(frame, orient="vertical", command=tree.yview)
        tree.configure(yscrollcommand=scrollbar.set)
        tree.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")

        for item in reversed(downloaded):
            overview = email_overview(item.path)
            tree.insert(
                "",
                "end",
                values=(item.uid, overview["date"], overview["from"], overview["subject"]),
            )
        ttk.Button(window, text="关闭", command=window.destroy).pack(pady=(0, 10))

    def _open_reports(self) -> None:
        try:
            self.reports_dir.mkdir(parents=True, exist_ok=True)
            os.startfile(self.reports_dir)
        except Exception as exc:
            self._show_error("无法打开结果文件夹", exc)

    def _show_error(self, title: str, exc: Exception) -> None:
        self.status_var.set(f"{title}：{exc}")
        messagebox.showerror(title, str(exc))

    def _show_text_dialog(self, title: str, content: str) -> None:
        window = tk.Toplevel(self.root)
        window.title(title)
        window.geometry("560x560")
        window.minsize(460, 360)
        window.transient(self.root)
        frame = ttk.Frame(window, padding=12)
        frame.pack(fill="both", expand=True)
        text = tk.Text(frame, wrap="word", font=("Microsoft YaHei UI", 10), padx=8, pady=8)
        scrollbar = ttk.Scrollbar(frame, orient="vertical", command=text.yview)
        text.configure(yscrollcommand=scrollbar.set)
        text.insert("1.0", content)
        text.configure(state="disabled")
        text.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")
        ttk.Button(window, text="确定", command=window.destroy).pack(pady=(0, 12))
        window.grab_set()


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    if "--smoke-test" in args:
        root = tk.Tk()
        root.withdraw()
        InquiryRouterApp(root)
        root.update_idletasks()
        root.destroy()
        return 0
    root = tk.Tk()
    InquiryRouterApp(root)
    root.mainloop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
