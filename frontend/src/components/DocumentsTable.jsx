export default function DocumentsTable({ docs, onDelete }) {
  if (!docs) return <p className="hint">Loading documents…</p>;
  if (docs.length === 0) return <p className="hint">No documents indexed yet.</p>;
  return (
    <table className="docs">
      <thead>
        <tr>
          <th>Title</th>
          <th>ID</th>
          <th>Version</th>
          <th>Status</th>
          <th>Roles</th>
          <th>Chunks</th>
          <th />
        </tr>
      </thead>
      <tbody>
        {docs.map((d) => (
          <tr key={d.doc_id}>
            <td>{d.title}</td>
            <td><code>{d.doc_id}</code></td>
            <td>{d.version}</td>
            <td>{d.status}</td>
            <td>{(d.allowed_roles || []).join(", ")}</td>
            <td>{d.chunks}</td>
            <td><button className="link danger" onClick={() => onDelete(d)}>Delete</button></td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}
