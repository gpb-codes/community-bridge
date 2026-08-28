import "./globals.css";

async function getData() {
  const key = process.env.NEXT_PUBLIC_ADMIN_API_KEY || "change-me-in-production";
  const base = process.env.API_BASE || "http://localhost:8000";
  const headers = { Authorization: `Bearer ${key}` };
  try {
    const [dash, maps] = await Promise.all([
      fetch(`${base}/api/v1/dashboard`, { headers, cache: "no-store" }),
      fetch(`${base}/api/v1/mappings`, { headers, cache: "no-store" }),
    ]);
    return {
      dash: dash.ok ? await dash.json() : null,
      maps: maps.ok ? await maps.json() : [],
    };
  } catch {
    return { dash: null, maps: [] };
  }
}

export default async function Page() {
  const { dash, maps } = await getData();
  return (
    <>
      <header><h1>🛰️ Community Bridge</h1></header>
      <main className="container">
        <section className="card">
          <h2>Dashboard</h2>
          {dash ? (
            <div className="grid">
              <div className="stat"><b>{dash.whatsapp}</b>WhatsApp</div>
              <div className="stat"><b>{dash.discord}</b>Discord</div>
              <div className="stat"><b>{dash.mappings_total}</b>Mappings</div>
              <div className="stat"><b>{dash.mappings_active}</b>Active</div>
              <div className="stat"><b>{dash.mappings_pending}</b>Pending</div>
              <div className="stat"><b>{dash.mappings_error}</b>Errors</div>
              <div className="stat"><b>{dash.messages_today}</b>Msgs today</div>
            </div>
          ) : (
            <p>Backend not reachable. Provide ADMIN_API_KEY and ensure the API is up.</p>
          )}
        </section>

        <section className="card">
          <h2>Mappings</h2>
          <table>
            <thead><tr><th>WhatsApp Group</th><th>Discord Channel</th><th>Status</th><th>Direction</th></tr></thead>
            <tbody>
              {maps.map((m: any) => (
                <tr key={m.id}>
                  <td>{m.whatsapp_group_id || "—"}</td>
                  <td>{m.discord_channel_id || "—"}</td>
                  <td><span className={`pill ${m.status}`}>{m.status}</span></td>
                  <td>{m.direction}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </section>
      </main>
    </>
  );
}
