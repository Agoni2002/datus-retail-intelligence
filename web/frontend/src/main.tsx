import {
  useEffect,
  useRef,
  useState,
  type FormEvent,
  type ReactNode,
} from "react";
import { createRoot } from "react-dom/client";
import {
  Activity,
  BarChart3,
  Box,
  CircleAlert,
  Database,
  LayoutDashboard,
  LockKeyhole,
  Send,
  ShieldCheck,
  Sparkles,
} from "lucide-react";
import { embedDashboard } from "@superset-ui/embedded-sdk";
import "./style.css";

const navigation = [
  { path: "/", label: "概览", icon: LayoutDashboard },
  { path: "/analytics", label: "经营分析", icon: BarChart3 },
  { path: "/analyst", label: "AI 分析师", icon: Sparkles },
  { path: "/quality", label: "数据质量", icon: ShieldCheck },
  { path: "/data", label: "数据管理", icon: Database },
];
const sourceNames: Record<string, string> = {
  customers: "客户",
  geolocation: "地理位置",
  order_items: "订单明细",
  order_payments: "订单付款",
  order_reviews: "订单评价",
  orders: "订单",
  products: "商品",
  sellers: "卖家",
  product_category_name_translation: "商品类别翻译",
};
const metricNames: Record<string, string> = {
  delivered_gmv: "已交付商品交易额",
  delivered_order_count: "已交付订单数",
  average_order_value: "平均客单价",
  cancellation_rate: "订单取消率",
  on_time_delivery_rate: "准时交付率",
  average_late_delivery_days: "平均延迟交付天数",
  freight_revenue: "运费收入",
  average_review_score: "平均评价分",
  repeat_purchase_rate: "同月复购率",
  category_sales: "类别销售额",
  seller_performance: "卖家表现",
};
const fmt = new Intl.NumberFormat("zh-CN");
const money = new Intl.NumberFormat("zh-CN", {
  style: "currency",
  currency: "BRL",
  currencyDisplay: "code",
});
const pct = new Intl.NumberFormat("zh-CN", {
  style: "percent",
  maximumFractionDigits: 4,
});
type Overview = {
  metrics: Record<string, number>;
  monthly: [string, number, number][];
  coverage: string[];
  coverageNote: string;
  version: string;
  warningCount: number;
};
type Quality = {
  checks: number;
  blockers: number;
  warnings: number;
  findings: string[];
  coverage: string;
};
type Snapshot = {
  version: string;
  sha256: string;
  published: string;
  size: number;
  coverage: string[];
  sources: [string, number][];
  layers: string[][];
  metrics: Record<
    string,
    { meaning: string; formula: string; limitations: string }
  >;
};
type Dashboard = { slug: string; uuid: string; title: string };
type Status = { enabled: boolean; message: string };
type Evidence = { columns: string[]; rows: unknown[][]; sql?: string };
type Answer = {
  answer: string;
  evidence: Evidence[];
  metric_ids: string[];
  limitations: string[];
};

async function api<T>(path: string, body?: object): Promise<T> {
  const response = await fetch(
    path,
    body
      ? {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(body),
        }
      : {},
  );
  const result = await response.json().catch(() => null);
  if (!response.ok)
    throw new Error(
      (
        {
          403: "没有权限执行此操作。",
          413: "提交的内容过长。",
          422: "请检查提交的内容。",
          429: "请求次数已达上限，请稍后重试。",
          503: "服务暂不可用，请稍后重试。",
          504: "分析超时，请重试。",
        } as Record<number, string>
      )[response.status] ?? "请求未能完成，请稍后重试。",
    );
  return result as T;
}

function Resource<T>({
  endpoint,
  children,
}: {
  endpoint: string;
  children: (data: T) => ReactNode;
}) {
  const [data, setData] = useState<T>();
  const [error, setError] = useState("");
  useEffect(() => {
    let current = true;
    api<T>(endpoint)
      .then((value) => current && setData(value))
      .catch(
        (cause) =>
          current &&
          setError(
            cause instanceof Error && !(cause instanceof TypeError)
              ? cause.message
              : "数据加载失败，请重试。",
          ),
      );
    return () => {
      current = false;
    };
  }, [endpoint]);
  return error ? (
    <p className="notice" role="alert">
      {error}
    </p>
  ) : data ? (
    children(data)
  ) : (
    <p role="status">正在加载已发布的数据…</p>
  );
}

function Heading({
  title,
  description,
}: {
  title: string;
  description: string;
}) {
  return (
    <header className="heading">
      <h1>{title}</h1>
      <p>{description}</p>
    </header>
  );
}

function Stat({
  label,
  value,
  note,
}: {
  label: string;
  value: string | number;
  note?: string;
}) {
  return (
    <section className="stat">
      <span>{label}</span>
      <strong>{value}</strong>
      {note && <small>{note}</small>}
    </section>
  );
}

function MonthlyChart({ monthly }: { monthly: Overview["monthly"] }) {
  const [mode, setMode] = useState<"gmv" | "orders">("gmv");
  const index = mode === "gmv" ? 1 : 2;
  const top = Math.max(1, ...monthly.map((row) => row[index]));
  const [selected, setSelected] = useState<string>();
  const point = monthly.find((row) => row[0] === selected);
  return (
    <section className="panel monthly">
      <div className="panel-header">
        <div>
          <h2>月度经营表现</h2>
          <p>按下单月份统计已交付订单</p>
        </div>
        <div className="segmented">
          <button aria-pressed={mode === "gmv"} onClick={() => setMode("gmv")}>
            交易额
          </button>
          <button
            aria-pressed={mode === "orders"}
            onClick={() => setMode("orders")}
          >
            订单量
          </button>
        </div>
      </div>
      <div
        className="plot"
        aria-label={
          mode === "gmv" ? "月度已交付商品交易额" : "月度已交付订单数"
        }
      >
        {monthly.map((row) => (
          <button
            key={row[0]}
            className={selected === row[0] ? "active" : ""}
            onMouseEnter={() => setSelected(row[0])}
            onFocus={() => setSelected(row[0])}
            onClick={() => setSelected(row[0])}
            aria-label={`${row[0].slice(0, 7)} ${mode === "gmv" ? money.format(row[index]) : fmt.format(row[index])}`}
          >
            <svg
              viewBox="0 0 10 100"
              preserveAspectRatio="none"
              aria-hidden="true"
            >
              <rect
                x="0"
                width="10"
                y={100 - Math.max(0.8, (row[index] / top) * 100)}
                height={Math.max(0.8, (row[index] / top) * 100)}
              />
            </svg>
          </button>
        ))}
      </div>
      <div className="plot-labels">
        <span>{monthly[0]?.[0].slice(0, 7)}</span>
        <span aria-live="polite">
          {point &&
            `${point[0].slice(0, 7)} · ${mode === "gmv" ? money.format(point[index]) : fmt.format(point[index])}`}
        </span>
        <span>{monthly.at(-1)?.[0].slice(0, 7)}</span>
      </div>
    </section>
  );
}

function OverviewPage() {
  return (
    <>
      <Heading
        title="电商经营概览"
        description="基于已发布的 Olist 数据仓库查看销售和履约表现。"
      />
      <Resource<Overview> endpoint="/api/public/overview">
        {(data) => (
          <>
            <div className="stats">
              <Stat
                label="已交付商品交易额"
                value={money.format(data.metrics.gmv)}
                note="商品金额，不含运费"
              />
              <Stat
                label="已交付订单数"
                value={fmt.format(data.metrics.orders)}
                note="状态为已交付的订单"
              />
              <Stat
                label="平均客单价"
                value={money.format(data.metrics.aov)}
                note="已交付商品交易额 ÷ 已交付订单数"
              />
              <Stat
                label="订单取消率"
                value={pct.format(data.metrics.cancellation)}
                note="占全部订单的比例"
              />
              <Stat
                label="准时交付率"
                value={pct.format(data.metrics.onTime)}
                note="以符合统计条件的已交付订单为基数"
              />
              <Stat
                label="平均评价分"
                value={data.metrics.review.toFixed(4)}
                note="采用每笔已交付订单的最新评价"
              />
            </div>
            <MonthlyChart monthly={data.monthly} />
            <div className="grid-two">
              <section className="panel">
                <h2>数据覆盖范围</h2>
                <p>{data.coverageNote}</p>
              </section>
              <section className="panel">
                <h2>已发布快照</h2>
                <p className="mono">{data.version}</p>
                <a href="/quality">查看 {data.warningCount} 条质量警告</a>
              </section>
            </div>
          </>
        )}
      </Resource>
    </>
  );
}

function DashboardFrame({ dashboard }: { dashboard: Dashboard }) {
  const mount = useRef<HTMLDivElement>(null);
  const [error, setError] = useState("");
  const [ready, setReady] = useState(false);
  useEffect(() => {
    let current = true;
    let detach: (() => void) | undefined;
    setError("");
    setReady(false);
    if (mount.current) {
      embedDashboard({
        id: dashboard.uuid,
        supersetDomain: window.location.origin,
        mountPoint: mount.current,
        fetchGuestToken: async () =>
          (
            await api<{ token: string }>("/api/superset/guest-token", {
              dashboard: dashboard.slug,
            })
          ).token,
        dashboardUiConfig: {
          hideTitle: true,
          hideChartControls: true,
          filters: { expanded: false },
        },
        referrerPolicy: "same-origin",
      })
        .then((embedded) => {
          if (!current) {
            embedded.unmount();
            return;
          }
          detach = () => embedded.unmount();
          const frame = mount.current?.querySelector("iframe");
          if (frame) frame.title = dashboard.title;
          setReady(true);
        })
        .catch(() => current && setError("仪表板加载失败，请刷新后重试。"));
    }
    return () => {
      current = false;
      detach?.();
    };
  }, [dashboard]);
  return (
    <>
      {!ready && (
        <p role={error ? "alert" : "status"}>{error || "正在打开仪表板…"}</p>
      )}
      <div className="embed" ref={mount} aria-label={dashboard.title} />
    </>
  );
}

function Analytics({ dashboards }: { dashboards: Dashboard[] }) {
  const [selected, setSelected] = useState(dashboards[0]?.slug);
  const active = dashboards.find((dashboard) => dashboard.slug === selected);
  return (
    <>
      <div className="tabs" aria-label="仪表板">
        {dashboards.map((dashboard) => (
          <button
            key={dashboard.slug}
            aria-pressed={selected === dashboard.slug}
            onClick={() => setSelected(dashboard.slug)}
          >
            {dashboard.title}
          </button>
        ))}
      </div>
      {active && <DashboardFrame key={active.slug} dashboard={active} />}
    </>
  );
}

function DataQuality() {
  return (
    <>
      <Heading
        title="数据质量"
        description="查看当前快照的校验结果和已知数据限制。"
      />
      <Resource<Quality> endpoint="/api/public/quality">
        {(data) => (
          <>
            <div className="stats three">
              <Stat label="质量检查项" value={data.checks} />
              <Stat label="阻断错误" value={data.blockers} />
              <Stat label="警告" value={data.warnings} />
            </div>
            <section className="panel findings">
              <h2>已知数据限制</h2>
              {data.findings.map((finding) => (
                <div key={finding}>
                  <CircleAlert size={19} aria-hidden="true" />
                  <p>{finding}</p>
                </div>
              ))}
            </section>
            <section className="panel">
              <h2>数据覆盖范围</h2>
              <p>{data.coverage}</p>
            </section>
          </>
        )}
      </Resource>
    </>
  );
}

function DataTable({
  headings,
  rows,
}: {
  headings: string[];
  rows: unknown[][];
}) {
  return (
    <div className="table-scroll">
      <table>
        <thead>
          <tr>
            {headings.map((title, i) => (
              <th key={i}>{title}</th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((row, i) => (
            <tr key={i}>
              {row.map((value, j) => (
                <td key={j}>{String(value ?? "—")}</td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function DataManagement() {
  return (
    <>
      <Heading
        title="数据管理"
        description="查看发布信息、数据仓库覆盖范围和指标口径。"
      />
      <Resource<Snapshot> endpoint="/api/public/snapshot">
        {(data) => (
          <>
            <section className="panel">
              <h2>当前发布版本</h2>
              <dl className="metadata">
                <dt>版本</dt>
                <dd>{data.version}</dd>
                <dt>SHA-256</dt>
                <dd>{data.sha256}</dd>
                <dt>发布时间</dt>
                <dd>
                  {new Date(data.published).toLocaleString("zh-CN", {
                    timeZone: "Asia/Shanghai",
                    hour12: false,
                  }) + "（北京时间）"}
                </dd>
                <dt>下单日期范围</dt>
                <dd>{data.coverage.join(" 至 ")}</dd>
                <dt>快照大小</dt>
                <dd>{(data.size / 1048576).toFixed(2)} MiB</dd>
              </dl>
            </section>
            <div className="grid-two">
              <section className="panel">
                <h2>源数据行数</h2>
                <DataTable
                  headings={["来源", "行数"]}
                  rows={data.sources.map(([name, rows]) => [
                    sourceNames[name] ?? name,
                    fmt.format(rows),
                  ])}
                />
              </section>
              <section className="panel">
                <h2>数据仓库分层</h2>
                <DataTable
                  headings={["分层", "表数", "行数"]}
                  rows={data.layers}
                />
              </section>
            </div>
            <section className="panel">
              <h2>指标口径</h2>
              <div className="definitions">
                {Object.entries(data.metrics).map(([name, metric]) => (
                  <details key={name}>
                    <summary>{metricNames[name] ?? name}</summary>
                    <p>{metric.meaning}</p>
                    <p>{metric.formula}</p>
                    <p className="muted">{metric.limitations}</p>
                  </details>
                ))}
              </div>
            </section>
          </>
        )}
      </Resource>
    </>
  );
}

function Analyst({ status }: { status: Status }) {
  const [question, setQuestion] = useState("");
  const [turns, setTurns] = useState<
    { question: string; answer?: Answer; error?: string }[]
  >([]);
  const [pending, setPending] = useState(false);
  async function ask(event: FormEvent) {
    event.preventDefault();
    if (!status.enabled || pending || !question.trim()) return;
    const asked = question.trim();
    setQuestion("");
    setPending(true);
    setTurns((previous) => [...previous, { question: asked }]);
    try {
      const answer = await api<Answer>("/api/ai/chat", { question: asked });
      setTurns((previous) => [
        ...previous.slice(0, -1),
        { question: asked, answer },
      ]);
    } catch (cause) {
      setTurns((previous) => [
        ...previous.slice(0, -1),
        { question: asked, error: (cause as Error).message },
      ]);
    } finally {
      setPending(false);
    }
  }
  return (
    <>
      <p className="notice" role="status">
        <LockKeyhole size={18} />
        {status.enabled
          ? "实时分析已启用。"
          : "实时 AI 尚未配置。你仍可查看经营分析和数据质量。"}
      </p>
      <div className="turns">
        {turns.map((turn, i) => (
          <section className="panel" key={i}>
            <h2>你的问题</h2>
            <p>{turn.question}</p>
            {turn.error && <p role="alert">{turn.error}</p>}
            {turn.answer && (
              <>
                <h2>分析结果</h2>
                <p>{turn.answer.answer}</p>
                <p>
                  参考指标 ·{" "}
                  {turn.answer.metric_ids
                    .map((id) => metricNames[id] ?? id)
                    .join("、")}
                </p>
                {turn.answer.evidence.map((item, j) => (
                  <div key={j}>
                    {item.sql && <pre>{item.sql}</pre>}
                    <DataTable headings={item.columns} rows={item.rows} />
                  </div>
                ))}
                {turn.answer.limitations.map((item) => (
                  <p key={item} className="muted">
                    {item}
                  </p>
                ))}
              </>
            )}
            {!turn.answer && !turn.error && (
              <p role="status">正在通过受控查询分析…</p>
            )}
          </section>
        ))}
      </div>
      <form className="panel ask" onSubmit={ask}>
        <label htmlFor="question">问题</label>
        <textarea
          id="question"
          value={question}
          onChange={(event) => setQuestion(event.target.value)}
          maxLength={4000}
          disabled={!status.enabled || pending}
          placeholder="每个下单月份的已交付商品交易额是多少？"
        />
        <button disabled={!status.enabled || pending || !question.trim()}>
          <Send size={16} /> 发送问题
        </button>
      </form>
    </>
  );
}

function App() {
  const current =
    navigation.find((item) => item.path === window.location.pathname) ||
    navigation[0];
  const page =
    current.path === "/analytics" ? (
      <>
        <Heading
          title="经营分析"
          description="通过六个交互式仪表板探索已发布的仓库数据。"
        />
        <Resource<Dashboard[]> endpoint="/api/public/dashboards">
          {(dashboards) => <Analytics dashboards={dashboards} />}
        </Resource>
      </>
    ) : current.path === "/analyst" ? (
      <>
        <Heading
          title="AI 分析师"
          description="用自然语言提问，由零售分析师通过受控查询访问数据仓库。"
        />
        <Resource<Status> endpoint="/api/ai/status">
          {(status) => <Analyst status={status} />}
        </Resource>
      </>
    ) : current.path === "/quality" ? (
      <DataQuality />
    ) : current.path === "/data" ? (
      <DataManagement />
    ) : (
      <OverviewPage />
    );
  return (
    <div className="shell">
      <aside className="sidebar">
        <a className="brand" href="/">
          <span>
            <Box size={22} />
          </span>
          <div>
            Datus <small>零售数据分析</small>
          </div>
        </a>
        <nav aria-label="主导航">
          {navigation.map(({ path, label, icon: Icon }) => (
            <a
              key={path}
              href={path}
              aria-current={path === current.path ? "page" : undefined}
            >
              <Icon size={18} />
              {label}
            </a>
          ))}
        </nav>
        <div className="side-foot">
          <LockKeyhole size={16} /> 只读演示
        </div>
      </aside>
      <div className="workspace">
        <div className="topbar">
          <span>{current.label}</span>
          <span className="publication">
            <Activity size={16} /> Olist 数据仓库
          </span>
        </div>
        <main id="main">{page}</main>
      </div>
    </div>
  );
}

createRoot(document.getElementById("root")!).render(<App />);
