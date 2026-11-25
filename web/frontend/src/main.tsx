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
  { path: "/", label: "Overview", icon: LayoutDashboard },
  { path: "/analytics", label: "Business Analytics", icon: BarChart3 },
  { path: "/analyst", label: "AI Analyst", icon: Sparkles },
  { path: "/quality", label: "Data Quality", icon: ShieldCheck },
  { path: "/data", label: "Data Management", icon: Database },
];
const fmt = new Intl.NumberFormat("en-US");
const money = new Intl.NumberFormat("en-US", {
  style: "currency",
  currency: "BRL",
  currencyDisplay: "code",
});
const pct = new Intl.NumberFormat("en-US", {
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
  const result = await response.json();
  if (!response.ok)
    throw new Error(
      typeof result.detail === "string"
        ? result.detail
        : "The request could not be completed.",
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
      .catch((cause) => current && setError(cause.message));
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
    <p role="status">Loading published data…</p>
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
          <h2>Monthly performance</h2>
          <p>Purchase month · delivered orders</p>
        </div>
        <div className="segmented">
          <button aria-pressed={mode === "gmv"} onClick={() => setMode("gmv")}>
            GMV
          </button>
          <button
            aria-pressed={mode === "orders"}
            onClick={() => setMode("orders")}
          >
            Orders
          </button>
        </div>
      </div>
      <div
        className="plot"
        aria-label={
          mode === "gmv" ? "Monthly delivered GMV" : "Monthly delivered orders"
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
        title="Marketplace overview"
        description="Fulfillment and commercial performance from the published Olist warehouse."
      />
      <Resource<Overview> endpoint="/api/public/overview">
        {(data) => (
          <>
            <div className="stats">
              <Stat
                label="Delivered GMV"
                value={money.format(data.metrics.gmv)}
                note="Merchandise value, excluding freight"
              />
              <Stat
                label="Delivered orders"
                value={fmt.format(data.metrics.orders)}
                note="Orders marked delivered"
              />
              <Stat
                label="Average order value"
                value={money.format(data.metrics.aov)}
                note="GMV per delivered order"
              />
              <Stat
                label="Cancellation rate"
                value={pct.format(data.metrics.cancellation)}
                note="Share of all observed orders"
              />
              <Stat
                label="On-time delivery"
                value={pct.format(data.metrics.onTime)}
                note="Eligible delivered orders"
              />
              <Stat
                label="Average review score"
                value={data.metrics.review.toFixed(4)}
                note="Latest review per delivered order"
              />
            </div>
            <MonthlyChart monthly={data.monthly} />
            <div className="grid-two">
              <section className="panel">
                <h2>Source coverage</h2>
                <p>{data.coverageNote}</p>
              </section>
              <section className="panel">
                <h2>Published snapshot</h2>
                <p className="mono">{data.version}</p>
                <a href="/quality">{data.warningCount} quality warnings</a>
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
          setReady(true);
        })
        .catch((cause) => current && setError(cause.message));
    }
    return () => {
      current = false;
      detach?.();
    };
  }, [dashboard]);
  return (
    <>
      {!ready && (
        <p role={error ? "alert" : "status"}>{error || "Opening dashboard…"}</p>
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
      <div className="tabs" aria-label="Dashboards">
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
        title="Data quality"
        description="Validation results and known limitations for the current publication."
      />
      <Resource<Quality> endpoint="/api/public/quality">
        {(data) => (
          <>
            <div className="stats three">
              <Stat label="Quality checks" value={data.checks} />
              <Stat label="Blocking errors" value={data.blockers} />
              <Stat label="Warnings" value={data.warnings} />
            </div>
            <section className="panel findings">
              <h2>Known limitations</h2>
              {data.findings.map((finding) => (
                <div key={finding}>
                  <CircleAlert size={19} aria-hidden="true" />
                  <p>{finding}</p>
                </div>
              ))}
            </section>
            <section className="panel">
              <h2>Source coverage</h2>
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
        title="Data management"
        description="Publication metadata, warehouse coverage and metric definitions."
      />
      <Resource<Snapshot> endpoint="/api/public/snapshot">
        {(data) => (
          <>
            <section className="panel">
              <h2>Current publication</h2>
              <dl className="metadata">
                <dt>Version</dt>
                <dd>{data.version}</dd>
                <dt>SHA-256</dt>
                <dd>{data.sha256}</dd>
                <dt>Published</dt>
                <dd>{new Date(data.published).toUTCString()}</dd>
                <dt>Purchase coverage</dt>
                <dd>{data.coverage.join(" to ")}</dd>
                <dt>Size</dt>
                <dd>{(data.size / 1048576).toFixed(2)} MiB</dd>
              </dl>
            </section>
            <div className="grid-two">
              <section className="panel">
                <h2>Source row counts</h2>
                <DataTable
                  headings={["Source", "Rows"]}
                  rows={data.sources.map(([name, rows]) => [
                    name.replaceAll("_", " "),
                    fmt.format(rows),
                  ])}
                />
              </section>
              <section className="panel">
                <h2>Warehouse layers</h2>
                <DataTable
                  headings={["Layer", "Tables", "Rows"]}
                  rows={data.layers}
                />
              </section>
            </div>
            <section className="panel">
              <h2>Metric definitions</h2>
              <div className="definitions">
                {Object.entries(data.metrics).map(([name, metric]) => (
                  <details key={name}>
                    <summary>{name.replaceAll("_", " ")}</summary>
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
        {status.message}
      </p>
      <div className="turns">
        {turns.map((turn, i) => (
          <section className="panel" key={i}>
            <h2>Your question</h2>
            <p>{turn.question}</p>
            {turn.error && <p role="alert">{turn.error}</p>}
            {turn.answer && (
              <>
                <h2>Analyst response</h2>
                <p>{turn.answer.answer}</p>
                <p>Source metrics · {turn.answer.metric_ids.join(", ")}</p>
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
              <p role="status">Running guarded analysis…</p>
            )}
          </section>
        ))}
      </div>
      <form className="panel ask" onSubmit={ask}>
        <label htmlFor="question">Question</label>
        <textarea
          id="question"
          value={question}
          onChange={(event) => setQuestion(event.target.value)}
          maxLength={4000}
          disabled={!status.enabled || pending}
          placeholder="What was delivered GMV by purchase month?"
        />
        <button disabled={!status.enabled || pending || !question.trim()}>
          <Send size={16} /> Send question
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
          title="Business analytics"
          description="Explore six interactive dashboards connected to the published warehouse."
        />
        <Resource<Dashboard[]> endpoint="/api/public/dashboards">
          {(dashboards) => <Analytics dashboards={dashboards} />}
        </Resource>
      </>
    ) : current.path === "/analyst" ? (
      <>
        <Heading
          title="AI analyst"
          description="Ask questions about the warehouse through the guarded Retail Analyst."
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
            Datus <small>Retail Intelligence</small>
          </div>
        </a>
        <nav aria-label="Main navigation">
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
          <LockKeyhole size={16} /> Read-only portfolio demo
        </div>
      </aside>
      <div className="workspace">
        <div className="topbar">
          <span>{current.label}</span>
          <span className="publication">
            <Activity size={16} /> Olist warehouse
          </span>
        </div>
        <main id="main">{page}</main>
      </div>
    </div>
  );
}

createRoot(document.getElementById("root")!).render(<App />);
