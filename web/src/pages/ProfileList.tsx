import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  Button,
  Input,
  Select,
  Space,
  Table,
  Tooltip,
  Popconfirm,
  message,
  Upload,
  Empty,
  Tag,
  Spin,
} from "antd";
import type { ColumnsType } from "antd/es/table";
import type { TableRowSelection } from "antd/es/table/interface";
import {
  PlusOutlined,
  PlayCircleOutlined,
  PauseCircleOutlined,
  EditOutlined,
  DeleteOutlined,
  ImportOutlined,
  ExportOutlined,
  SearchOutlined,
  ReloadOutlined,
  PoweroffOutlined,
  CheckCircleFilled,
  CloseCircleFilled,
  MinusCircleFilled,
  LoadingOutlined,
  GlobalOutlined,
} from "@ant-design/icons";
import StatusBadge from "../components/StatusBadge";
import TagManager from "../components/TagManager";
import { formatProxy } from "../api/client";
import ProfileEdit from "./ProfileEdit";
import type { Profile, BrowserStatus, ProxyCheckResult } from "../api/client";
import {
  listProfiles,
  deleteProfile,
  bulkDelete,
  importProfiles,
  exportProfiles,
  startBrowser,
  stopBrowser,
  stopAllBrowsers,
  getAllBrowserStatus,
  getTags,
  checkProxy,
} from "../api/client";

type StatusFilter = "all" | "running" | "stopped";

/** Country code -> flag emoji */
function countryFlag(code: string): string {
  if (!code || code.length !== 2) return "";
  const offset = 0x1f1e6;
  return (
    String.fromCodePoint(code.charCodeAt(0) - 97 + offset) +
    String.fromCodePoint(code.charCodeAt(1) - 97 + offset)
  );
}

export default function ProfileList() {
  /* ---------------------------------------------------------------- */
  /*  State                                                            */
  /* ---------------------------------------------------------------- */
  const [profiles, setProfiles] = useState<Profile[]>([]);
  const [browserMap, setBrowserMap] = useState<Record<string, BrowserStatus>>(
    {}
  );
  const [tags, setTags] = useState<string[]>([]);
  const [loading, setLoading] = useState(false);
  const [search, setSearch] = useState("");
  const [tagFilter, setTagFilter] = useState<string | undefined>(undefined);
  const [statusFilter, setStatusFilter] = useState<StatusFilter>("all");
  const [selectedKeys, setSelectedKeys] = useState<React.Key[]>([]);

  // Proxy check state: name -> result
  const [proxyStatus, setProxyStatus] = useState<
    Record<string, ProxyCheckResult & { loading?: boolean }>
  >({});

  // Modal
  const [editOpen, setEditOpen] = useState(false);
  const [editProfile, setEditProfile] = useState<Profile | null>(null);

  // Auto-refresh
  const timerRef = useRef<ReturnType<typeof setInterval> | null>(null);

  /* ---------------------------------------------------------------- */
  /*  Data fetching                                                    */
  /* ---------------------------------------------------------------- */
  const fetchProfiles = useCallback(async () => {
    setLoading(true);
    try {
      const [profs, bMap, tagList] = await Promise.all([
        listProfiles(tagFilter),
        getAllBrowserStatus(),
        getTags(),
      ]);
      setProfiles(profs);
      setBrowserMap(bMap);
      setTags(tagList);
    } catch (err) {
      console.error("Failed to fetch profiles", err);
    } finally {
      setLoading(false);
    }
  }, [tagFilter]);

  const refreshBrowserStatus = useCallback(async () => {
    try {
      const bMap = await getAllBrowserStatus();
      setBrowserMap(bMap);
    } catch {
      /* silent */
    }
  }, []);

  useEffect(() => {
    fetchProfiles();
  }, [fetchProfiles]);

  /* Auto-refresh browser status every 5 seconds */
  useEffect(() => {
    timerRef.current = setInterval(refreshBrowserStatus, 5000);
    return () => {
      if (timerRef.current) clearInterval(timerRef.current);
    };
  }, [refreshBrowserStatus]);

  /* Auto check proxies — disabled, only check on click or start */

  const handleCheckSingleProxy = async (name: string) => {
    setProxyStatus((prev) => ({
      ...prev,
      [name]: { status: "alive", loading: true },
    }));
    try {
      const result = await checkProxy(name);
      setProxyStatus((prev) => ({
        ...prev,
        [name]: { ...result, loading: false },
      }));
    } catch {
      setProxyStatus((prev) => ({
        ...prev,
        [name]: { status: "dead", message: "Check failed", loading: false },
      }));
    }
  };

  /* ---------------------------------------------------------------- */
  /*  Filtered data source                                             */
  /* ---------------------------------------------------------------- */
  const dataSource = useMemo(() => {
    let list = profiles;

    // Search
    if (search) {
      const q = search.toLowerCase();
      list = list.filter((p) => p.name.toLowerCase().includes(q));
    }

    // Status filter
    if (statusFilter === "running") {
      list = list.filter((p) => browserMap[p.name]?.alive);
    } else if (statusFilter === "stopped") {
      list = list.filter((p) => !browserMap[p.name]?.alive);
    }

    return list;
  }, [profiles, search, statusFilter, browserMap]);

  /* ---------------------------------------------------------------- */
  /*  Actions                                                          */
  /* ---------------------------------------------------------------- */
  const handleStart = async (name: string) => {
    // Pause auto-refresh during the operation
    if (timerRef.current) clearInterval(timerRef.current);
    try {
      await startBrowser(name);
      message.success(`Browser "${name}" started`);
      // Immediately update local state
      setBrowserMap((prev) => ({
        ...prev,
        [name]: { alive: true, uptime: 0, url: "" },
      }));
      // Check proxy after starting
      handleCheckSingleProxy(name);
    } catch (err: any) {
      message.error(
        err?.response?.data?.detail ?? "Failed to start browser"
      );
    } finally {
      await refreshBrowserStatus();
      timerRef.current = setInterval(refreshBrowserStatus, 5000);
    }
  };

  const handleStop = async (name: string) => {
    // Pause auto-refresh to prevent it from overwriting our optimistic update
    if (timerRef.current) clearInterval(timerRef.current);
    // Immediately update local state — button changes to Start right away
    setBrowserMap((prev) => ({
      ...prev,
      [name]: { alive: false, uptime: 0, url: "" },
    }));
    try {
      await stopBrowser(name);
      message.success(`Browser "${name}" stopped`);
    } catch (err: any) {
      message.error(
        err?.response?.data?.detail ?? "Failed to stop browser"
      );
    } finally {
      // Give server a moment to fully clean up, then refresh from server
      setTimeout(async () => {
        await refreshBrowserStatus();
        // Resume auto-refresh
        timerRef.current = setInterval(refreshBrowserStatus, 5000);
      }, 500);
    }
  };

  const handleDelete = async (name: string) => {
    try {
      await deleteProfile(name);
      message.success(`Deleted "${name}"`);
      fetchProfiles();
    } catch (err: any) {
      message.error(err?.response?.data?.detail ?? "Delete failed");
    }
  };

  const handleBulkDelete = async () => {
    try {
      const result = await bulkDelete(selectedKeys as string[]);
      message.success(`Deleted ${result.deleted.length} profiles`);
      setSelectedKeys([]);
      fetchProfiles();
    } catch {
      message.error("Bulk delete failed");
    }
  };

  const handleBulkStart = async () => {
    const names = selectedKeys as string[];
    const stopped = names.filter((n) => !browserMap[n]?.alive);
    if (stopped.length === 0) {
      message.info("All selected browsers are already running");
      return;
    }
    message.loading({
      content: `Starting ${stopped.length} browsers...`,
      key: "bulk",
    });
    await Promise.allSettled(stopped.map((n) => startBrowser(n)));
    message.success({ content: "Done", key: "bulk" });
    await refreshBrowserStatus();
  };

  const handleBulkStop = async () => {
    const names = selectedKeys as string[];
    const running = names.filter((n) => browserMap[n]?.alive);
    if (running.length === 0) {
      message.info("No selected browsers are running");
      return;
    }
    message.loading({
      content: `Stopping ${running.length} browsers...`,
      key: "bulk",
    });
    await Promise.allSettled(running.map((n) => stopBrowser(n)));
    message.success({ content: "Done", key: "bulk" });
    // Immediately clear all stopped
    setBrowserMap((prev) => {
      const next = { ...prev };
      for (const n of running) {
        next[n] = { alive: false, uptime: 0, url: "" };
      }
      return next;
    });
  };

  const handleStopAll = async () => {
    try {
      await stopAllBrowsers();
      message.success("All browsers stopped");
      // Immediately clear all
      setBrowserMap((prev) => {
        const next: Record<string, BrowserStatus> = {};
        for (const [k] of Object.entries(prev)) {
          next[k] = { alive: false, uptime: 0, url: "" };
        }
        return next;
      });
    } catch {
      message.error("Failed to stop all browsers");
    }
  };

  const handleImport = async (file: File) => {
    try {
      const result = await importProfiles(file);
      message.success(
        `Imported: ${result.total_created} created, ${result.skipped.length} skipped`
      );
      fetchProfiles();
    } catch (err: any) {
      message.error(err?.response?.data?.detail ?? "Import failed");
    }
  };

  const handleExport = async () => {
    try {
      const blob = await exportProfiles();
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = "camo-profiles.json";
      a.click();
      URL.revokeObjectURL(url);
    } catch {
      message.error("Export failed");
    }
  };

  /* ---------------------------------------------------------------- */
  /*  Proxy status renderer                                            */
  /* ---------------------------------------------------------------- */
  const renderProxyStatus = (record: Profile) => {
    if (!record.proxy) {
      return <span className="proxy-no">No proxy</span>;
    }

    const ps = proxyStatus[record.name];

    // Not checked yet — show nothing (user can click to check)
    if (!ps) {
      return (
        <span className="proxy-no" style={{ cursor: "pointer" }} onClick={() => handleCheckSingleProxy(record.name)}>
          Click to check
        </span>
      );
    }

    // Loading
    if (ps.loading) {
      return (
        <span className="proxy-checking">
          <Spin indicator={<LoadingOutlined style={{ fontSize: 12 }} />} size="small" />
          <span>Checking...</span>
        </span>
      );
    }

    // Alive
    if (ps.status === "alive" && ps.ip) {
      const flag = ps.country_code ? countryFlag(ps.country_code) : "";
      return (
        <Tooltip title={`${ps.city ? ps.city + ", " : ""}${ps.country}`}>
          <span className="proxy-alive" onClick={() => handleCheckSingleProxy(record.name)}>
            <CheckCircleFilled style={{ color: "#22c55e", fontSize: 13 }} />
            <span className="proxy-ip">{ps.ip}</span>
            {flag && <span className="proxy-flag">{flag}</span>}
          </span>
        </Tooltip>
      );
    }

    // Dead
    if (ps.status === "dead") {
      return (
        <Tooltip title={ps.message || "Proxy unreachable"}>
          <span className="proxy-dead" onClick={() => handleCheckSingleProxy(record.name)}>
            <CloseCircleFilled style={{ color: "#ef4444", fontSize: 13 }} />
            <span>Proxy Die</span>
          </span>
        </Tooltip>
      );
    }

    // No proxy / invalid
    return (
      <span className="proxy-no">
        <MinusCircleFilled style={{ color: "#6b6b7e", fontSize: 13 }} />
        <span>{ps.message || "N/A"}</span>
      </span>
    );
  };

  /* ---------------------------------------------------------------- */
  /*  Table columns                                                    */
  /* ---------------------------------------------------------------- */
  const columns: ColumnsType<Profile> = [
    {
      title: "#",
      key: "index",
      width: 50,
      render: (_v, _r, i) => (
        <span style={{ color: "#4b4b5e", fontSize: 12 }}>{i + 1}</span>
      ),
    },
    {
      title: "Status",
      dataIndex: "name",
      key: "status",
      width: 100,
      render: (name: string) => {
        const bs = browserMap[name];
        return (
          <StatusBadge running={!!bs?.alive} currentUrl={bs?.url} />
        );
      },
    },
    {
      title: "Profile",
      dataIndex: "name",
      key: "name",
      sorter: (a, b) => a.name.localeCompare(b.name),
      render: (name: string, record: Profile) => (
        <div className="profile-name-cell">
          <span className="profile-name">{name}</span>
          {record.note && (
            <span className="profile-note">{record.note}</span>
          )}
        </div>
      ),
    },
    {
      title: (
        <span>
          <GlobalOutlined style={{ marginRight: 4 }} />
          Proxy
        </span>
      ),
      key: "proxy",
      width: 200,
      render: (_, record) => (
        <div className="proxy-cell">
          <span className="proxy-display">
            {record.proxy ? formatProxy(record.proxy, record.proxy_type) : "Direct"}
          </span>
          {renderProxyStatus(record)}
        </div>
      ),
    },
    {
      title: "Tags",
      dataIndex: "tags",
      key: "tags",
      width: 180,
      render: (tagList: string[]) =>
        tagList?.length ? (
          <TagManager tags={tagList} max={3} />
        ) : (
          <span style={{ color: "#4b4b5e" }}>{"\u2014"}</span>
        ),
    },
    {
      title: "Uses",
      dataIndex: "use_count",
      key: "use_count",
      width: 70,
      align: "center",
      sorter: (a, b) => (a.use_count ?? 0) - (b.use_count ?? 0),
      render: (v: number) => (
        <span className="use-count-badge">{v ?? 0}</span>
      ),
    },
    {
      title: "Size",
      dataIndex: "size_bytes",
      key: "size_bytes",
      width: 110,
      align: "center",
      sorter: (a, b) => (a.size_bytes ?? 0) - (b.size_bytes ?? 0),
      render: (v: number) => {
        if (!v) return <span style={{ color: "#4b4b5e", fontSize: 12 }}>0</span>;
        if (v < 1024) return <span className="size-badge">{v} B</span>;
        if (v < 1024 * 1024)
          return <span className="size-badge">{(v / 1024).toFixed(0)} KB</span>;
        if (v < 1024 * 1024 * 1024)
          return <span className="size-badge">{(v / (1024 * 1024)).toFixed(1)} MB</span>;
        return <span className="size-badge">{(v / (1024 * 1024 * 1024)).toFixed(2)} GB</span>;
      },
    },
    {
      title: "Last Used",
      dataIndex: "last_used",
      key: "last_used",
      width: 150,
      sorter: (a, b) =>
        new Date(a.last_used ?? 0).getTime() -
        new Date(b.last_used ?? 0).getTime(),
      render: (v: string | null) =>
        v ? (
          <span style={{ color: "#8b8b9e", fontSize: 12 }}>
            {new Date(v).toLocaleString()}
          </span>
        ) : (
          <span style={{ color: "#4b4b5e", fontSize: 12 }}>Never</span>
        ),
    },
    {
      title: "Actions",
      key: "actions",
      width: 200,
      fixed: "right",
      render: (_, record) => {
        const isRunning = browserMap[record.name]?.alive;
        return (
          <div className="row-actions">
            {isRunning ? (
              <Tooltip title="Stop Browser">
                <Button
                  type="text"
                  size="small"
                  className="action-btn stop-btn"
                  icon={<PauseCircleOutlined />}
                  onClick={() => handleStop(record.name)}
                >
                  Stop
                </Button>
              </Tooltip>
            ) : (
              <Tooltip title="Start Browser">
                <Button
                  type="text"
                  size="small"
                  className="action-btn start-btn"
                  icon={<PlayCircleOutlined />}
                  onClick={() => handleStart(record.name)}
                >
                  Start
                </Button>
              </Tooltip>
            )}
            <Tooltip title="Edit">
              <Button
                type="text"
                size="small"
                className="action-btn edit-btn"
                icon={<EditOutlined />}
                onClick={() => {
                  setEditProfile(record);
                  setEditOpen(true);
                }}
              />
            </Tooltip>
            <Popconfirm
              title="Delete this profile?"
              description="This action cannot be undone."
              onConfirm={() => handleDelete(record.name)}
              okText="Delete"
              okButtonProps={{ danger: true }}
            >
              <Tooltip title="Delete">
                <Button
                  type="text"
                  size="small"
                  danger
                  className="action-btn"
                  icon={<DeleteOutlined />}
                />
              </Tooltip>
            </Popconfirm>
          </div>
        );
      },
    },
  ];

  /* ---------------------------------------------------------------- */
  /*  Row selection                                                    */
  /* ---------------------------------------------------------------- */
  const rowSelection: TableRowSelection<Profile> = {
    selectedRowKeys: selectedKeys,
    onChange: (keys) => setSelectedKeys(keys),
  };

  /* ---------------------------------------------------------------- */
  /*  Summary stats                                                    */
  /* ---------------------------------------------------------------- */
  const runningCount = useMemo(
    () => Object.values(browserMap).filter((b) => b.alive).length,
    [browserMap]
  );
  const totalSize = useMemo(
    () => profiles.reduce((sum, p) => sum + (p.size_bytes ?? 0), 0),
    [profiles]
  );
  const formatSize = (bytes: number) => {
    if (bytes < 1024) return `${bytes} B`;
    if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(0)} KB`;
    if (bytes < 1024 * 1024 * 1024)
      return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
    return `${(bytes / (1024 * 1024 * 1024)).toFixed(2)} GB`;
  };

  /* ---------------------------------------------------------------- */
  /*  Render                                                           */
  /* ---------------------------------------------------------------- */
  return (
    <div className="profile-page">
      {/* ---- Stats bar ---- */}
      <div className="stats-bar">
        <div className="stat-card">
          <div className="stat-value">{profiles.length}</div>
          <div className="stat-label">Profiles</div>
        </div>
        <div className="stat-card">
          <div className="stat-value" style={{ color: "#22c55e" }}>
            {runningCount}
          </div>
          <div className="stat-label">Running</div>
        </div>
        <div className="stat-card">
          <div className="stat-value" style={{ color: "#3b82f6" }}>
            {profiles.filter((p) => p.proxy).length}
          </div>
          <div className="stat-label">With Proxy</div>
        </div>
        <div className="stat-card">
          <div className="stat-value" style={{ color: "#f59e0b", fontSize: 18 }}>
            {formatSize(totalSize)}
          </div>
          <div className="stat-label">Disk Usage</div>
        </div>
      </div>

      {/* ---- Toolbar ---- */}
      <div className="toolbar">
        <div className="toolbar-left">
          <Input
            prefix={<SearchOutlined style={{ color: "#6b6b7e" }} />}
            placeholder="Search profiles..."
            allowClear
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            style={{ width: 220 }}
            className="search-input"
          />
          <Select
            placeholder="Tag"
            allowClear
            value={tagFilter}
            onChange={(v) => setTagFilter(v)}
            style={{ width: 140 }}
            options={tags.map((t) => ({ value: t, label: t }))}
          />
          <Select
            value={statusFilter}
            onChange={(v) => setStatusFilter(v)}
            style={{ width: 120 }}
            options={[
              { value: "all", label: "All" },
              { value: "running", label: "Running" },
              { value: "stopped", label: "Stopped" },
            ]}
          />
        </div>
        <div className="toolbar-right">
          <Tooltip title="Refresh">
            <Button
              icon={<ReloadOutlined />}
              onClick={fetchProfiles}
              loading={loading}
              className="toolbar-btn"
            />
          </Tooltip>
          <Upload
            accept=".json"
            showUploadList={false}
            beforeUpload={(file) => {
              handleImport(file);
              return false;
            }}
          >
            <Tooltip title="Import">
              <Button icon={<ImportOutlined />} className="toolbar-btn" />
            </Tooltip>
          </Upload>
          <Tooltip title="Export">
            <Button
              icon={<ExportOutlined />}
              onClick={handleExport}
              className="toolbar-btn"
            />
          </Tooltip>
          <Button
            type="primary"
            icon={<PlusOutlined />}
            onClick={() => {
              setEditProfile(null);
              setEditOpen(true);
            }}
            className="new-profile-btn"
          >
            New Profile
          </Button>
        </div>
      </div>

      {/* ---- Bulk action bar ---- */}
      {selectedKeys.length > 0 && (
        <div className="bulk-bar">
          <span className="bulk-bar-count">
            {selectedKeys.length} selected
          </span>
          <Space>
            <Button
              size="small"
              icon={<PlayCircleOutlined />}
              onClick={handleBulkStart}
              className="bulk-start-btn"
            >
              Start
            </Button>
            <Button
              size="small"
              icon={<PauseCircleOutlined />}
              onClick={handleBulkStop}
            >
              Stop
            </Button>
            <Popconfirm
              title={`Delete ${selectedKeys.length} profiles?`}
              onConfirm={handleBulkDelete}
              okText="Delete"
              okButtonProps={{ danger: true }}
            >
              <Button size="small" danger icon={<DeleteOutlined />}>
                Delete
              </Button>
            </Popconfirm>
            <Button
              size="small"
              danger
              icon={<PoweroffOutlined />}
              onClick={handleStopAll}
            >
              Stop All
            </Button>
          </Space>
        </div>
      )}

      {/* ---- Table ---- */}
      <div className="table-card">
        <Table<Profile>
          className="profile-table"
          columns={columns}
          dataSource={dataSource}
          rowKey="name"
          rowSelection={rowSelection}
          loading={loading}
          pagination={{
            pageSize: 50,
            showSizeChanger: true,
            pageSizeOptions: ["20", "50", "100"],
            showTotal: (total) => (
              <span style={{ color: "#6b6b7e" }}>{total} profiles</span>
            ),
          }}
          locale={{
            emptyText: (
              <Empty
                image={Empty.PRESENTED_IMAGE_SIMPLE}
                description={
                  <div className="empty-state">
                    <div className="empty-state-text">
                      No profiles yet. Click{" "}
                      <strong style={{ color: "#7c3aed" }}>New Profile</strong>{" "}
                      to get started.
                    </div>
                  </div>
                }
              />
            ),
          }}
          size="middle"
          scroll={{ x: 1100 }}
        />
      </div>

      {/* ---- Edit Modal ---- */}
      <ProfileEdit
        open={editOpen}
        profile={editProfile}
        onClose={() => setEditOpen(false)}
        onSaved={fetchProfiles}
        existingTags={tags}
      />
    </div>
  );
}