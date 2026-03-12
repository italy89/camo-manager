import { Tooltip } from "antd";

interface StatusBadgeProps {
  running: boolean;
  currentUrl?: string;
}

export default function StatusBadge({ running, currentUrl }: StatusBadgeProps) {
  const badge = (
    <span className="status-badge">
      <span className={`status-dot ${running ? "running" : "stopped"}`} />
      <span style={{ color: running ? "#22c55e" : "#6b6b7e" }}>
        {running ? "Running" : "Stopped"}
      </span>
    </span>
  );

  if (running && currentUrl) {
    return <Tooltip title={currentUrl}>{badge}</Tooltip>;
  }

  return badge;
}
