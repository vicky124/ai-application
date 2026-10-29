import { Trash } from "./icons.jsx";

const statusStyle = {
  active: "bg-success-soft text-success",
  draft: "bg-warn-soft text-warn",
  inactive: "bg-surface-2 text-muted",
};

export default function DocumentsTable({ docs, onDelete }) {
  if (!docs) return <p className="px-6 pb-6 text-sm text-muted">Loading documents…</p>;
  if (docs.length === 0) return <p className="px-6 pb-6 text-sm text-muted">No documents indexed yet.</p>;
  return (
    <div className="overflow-x-auto">
      <table className="w-full min-w-[640px] text-left text-sm">
        <thead>
          <tr className="border-y border-border bg-surface-2/60 text-xs uppercase tracking-wide text-muted">
            {["Title", "ID", "Version", "Status", "Roles", "Chunks", ""].map((h, i) => (
              <th key={i} className="px-5 py-2.5 font-medium first:sm:pl-6">
                {h}
              </th>
            ))}
          </tr>
        </thead>
        <tbody className="divide-y divide-border">
          {docs.map((d) => (
            <tr key={d.doc_id} className="transition-colors hover:bg-surface-2/50">
              <td className="px-5 py-3 font-medium sm:pl-6">{d.title}</td>
              <td className="px-5 py-3">
                <code className="rounded-md bg-surface-2 px-1.5 py-0.5 text-xs">{d.doc_id}</code>
              </td>
              <td className="px-5 py-3 text-muted">{d.version}</td>
              <td className="px-5 py-3">
                <span className={`badge ${statusStyle[d.status] || statusStyle.inactive}`}>{d.status}</span>
              </td>
              <td className="px-5 py-3">
                <span className="flex flex-wrap gap-1">
                  {(d.allowed_roles || []).map((r) => (
                    <span key={r} className="badge bg-accent-soft text-accent-text">
                      {r}
                    </span>
                  ))}
                </span>
              </td>
              <td className="px-5 py-3 tabular-nums text-muted">{d.chunks}</td>
              <td className="px-5 py-3 text-right">
                <button
                  type="button"
                  onClick={() => onDelete(d)}
                  className="inline-flex cursor-pointer items-center gap-1.5 rounded-lg px-2 py-1 text-xs font-medium text-danger transition-colors hover:bg-danger-soft"
                  aria-label={`Delete ${d.title}`}
                >
                  <Trash className="size-3.5" /> Delete
                </button>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
