import { Tag } from "antd";

/* 12 pre-defined colours that recycle by tag-name hash */
const TAG_PALETTE = [
  "magenta",
  "red",
  "volcano",
  "orange",
  "gold",
  "lime",
  "green",
  "cyan",
  "blue",
  "geekblue",
  "purple",
  "#7c3aed",
];

function tagColor(tag: string): string {
  let hash = 0;
  for (let i = 0; i < tag.length; i++) {
    hash = tag.charCodeAt(i) + ((hash << 5) - hash);
  }
  return TAG_PALETTE[Math.abs(hash) % TAG_PALETTE.length];
}

interface TagManagerProps {
  tags: string[];
  /** If provided, clicking X calls this with the removed tag */
  onRemove?: (tag: string) => void;
  /** Max tags to display before showing +N more */
  max?: number;
}

export default function TagManager({
  tags,
  onRemove,
  max,
}: TagManagerProps) {
  const visible = max && tags.length > max ? tags.slice(0, max) : tags;
  const overflow = max && tags.length > max ? tags.length - max : 0;

  return (
    <span style={{ display: "inline-flex", flexWrap: "wrap", gap: 4 }}>
      {visible.map((t) => (
        <Tag
          key={t}
          color={tagColor(t)}
          closable={!!onRemove}
          onClose={(e) => {
            e.preventDefault();
            onRemove?.(t);
          }}
          className="profile-tag"
          style={{ marginRight: 0 }}
        >
          {t}
        </Tag>
      ))}
      {overflow > 0 && (
        <Tag className="profile-tag" style={{ marginRight: 0 }}>
          +{overflow}
        </Tag>
      )}
    </span>
  );
}

export { tagColor };
