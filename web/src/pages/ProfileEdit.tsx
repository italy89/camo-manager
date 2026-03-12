import { useEffect, useState } from "react";
import {
  Modal,
  Form,
  Input,
  InputNumber,
  Select,
  Descriptions,
  message,
  Divider,
  Space,
  Timeline,
} from "antd";
import {
  PlayCircleOutlined,
  PauseCircleOutlined,
} from "@ant-design/icons";
import ProxyEditor from "../components/ProxyEditor";
import type { Profile } from "../api/client";
import {
  createProfile,
  updateProfile,
  getProfile,
  parseProxyString,
  buildProxyString,
} from "../api/client";

interface ProfileEditProps {
  open: boolean;
  profile: Profile | null; // null => create mode
  onClose: () => void;
  onSaved: () => void;
  existingTags: string[];
}

const RESOLUTION_PRESETS = [
  { label: "1920 × 1080 (Full HD)", width: 1920, height: 1080 },
  { label: "1366 × 768 (HD)", width: 1366, height: 768 },
  { label: "1536 × 864", width: 1536, height: 864 },
  { label: "1440 × 900", width: 1440, height: 900 },
  { label: "1280 × 720 (720p)", width: 1280, height: 720 },
  { label: "Custom", width: 0, height: 0 },
];

export default function ProfileEdit({
  open,
  profile,
  onClose,
  onSaved,
  existingTags,
}: ProfileEditProps) {
  const [form] = Form.useForm();
  const isEdit = !!profile;
  const [history, setHistory] = useState<Array<{ action: string; timestamp: string }>>([]);

  /* Fetch full profile with history when editing */
  useEffect(() => {
    if (!open || !profile) {
      setHistory([]);
      return;
    }
    getProfile(profile.name)
      .then((full) => setHistory(full.history ?? []))
      .catch(() => setHistory([]));
  }, [open, profile]);

  /* Populate form when the modal opens */
  useEffect(() => {
    if (!open) return;
    if (profile) {
      const parsed = parseProxyString(profile.proxy, profile.proxy_type);
      const vp = profile.viewport;

      // Find matching preset
      let preset = "custom";
      if (vp?.width && vp?.height) {
        const found = RESOLUTION_PRESETS.find(
          (p) => p.width === vp.width && p.height === vp.height
        );
        if (found && found.width > 0) preset = `${found.width}x${found.height}`;
      } else {
        preset = "1920x1080"; // default
      }

      form.setFieldsValue({
        name: profile.name,
        proxy_type: profile.proxy ? parsed.type : "none",
        proxy_host: parsed.host,
        proxy_port: parsed.port,
        proxy_user: parsed.username,
        proxy_pass: parsed.password,
        tags: profile.tags ?? [],
        note: profile.note ?? "",
        resolution_preset: preset,
        viewport_width: vp?.width || 1920,
        viewport_height: vp?.height || 1080,
      });
    } else {
      form.resetFields();
      form.setFieldsValue({
        resolution_preset: "1920x1080",
        viewport_width: 1920,
        viewport_height: 1080,
      });
    }
  }, [open, profile, form]);

  const handlePresetChange = (val: string) => {
    if (val === "custom") return;
    const [w, h] = val.split("x").map(Number);
    form.setFieldsValue({ viewport_width: w, viewport_height: h });
  };

  const handleOk = async () => {
    try {
      const values = await form.validateFields();

      // Build proxy string from form fields
      let proxyStr: string | null = null;
      let proxyType = values.proxy_type || "http";
      if (proxyType !== "none" && values.proxy_host) {
        proxyStr = buildProxyString(
          values.proxy_host,
          values.proxy_port,
          values.proxy_user || "",
          values.proxy_pass || ""
        );
      } else {
        proxyType = "http";
      }

      // Build viewport
      const viewport =
        values.viewport_width && values.viewport_height
          ? { width: values.viewport_width, height: values.viewport_height }
          : undefined;

      if (isEdit) {
        await updateProfile(profile!.name, {
          proxy: proxyStr,
          proxy_type: proxyType,
          tags: values.tags ?? [],
          note: values.note ?? "",
          viewport: viewport ?? null,
        });
        message.success(`Profile "${profile!.name}" updated`);
      } else {
        await createProfile({
          name: values.name.trim(),
          proxy: proxyStr,
          proxy_type: proxyType,
          tags: values.tags ?? [],
          note: values.note ?? "",
        });
        message.success(`Profile "${values.name}" created`);
      }
      onSaved();
      onClose();
    } catch (err: any) {
      if (err?.errorFields) return; // form validation
      const msg =
        err?.response?.data?.detail ??
        err?.message ??
        "Unknown error";
      message.error(msg);
    }
  };

  return (
    <Modal
      className="profile-modal"
      title={isEdit ? `Edit \u2014 ${profile!.name}` : "New Profile"}
      open={open}
      onOk={handleOk}
      onCancel={onClose}
      okText={isEdit ? "Save" : "Create"}
      width={520}
      destroyOnClose
    >
      <Form
        form={form}
        layout="vertical"
        requiredMark="optional"
        style={{ marginTop: 16 }}
      >
        {/* -------- Name -------- */}
        <Form.Item
          name="name"
          label="Profile Name"
          rules={[
            { required: true, message: "Name is required" },
            {
              pattern: /^\S+$/,
              message: "No spaces allowed in name",
            },
          ]}
        >
          <Input placeholder="ACC001" disabled={isEdit} />
        </Form.Item>

        {/* -------- Proxy -------- */}
        <Divider orientation="left" plain style={{ borderColor: "#2a2a40" }}>
          Proxy
        </Divider>
        <ProxyEditor />

        {/* -------- Resolution -------- */}
        <Divider orientation="left" plain style={{ borderColor: "#2a2a40" }}>
          Resolution
        </Divider>
        <Form.Item name="resolution_preset" label="Preset">
          <Select
            options={RESOLUTION_PRESETS.map((p) => ({
              value: p.width > 0 ? `${p.width}x${p.height}` : "custom",
              label: p.label,
            }))}
            onChange={handlePresetChange}
          />
        </Form.Item>
        <Space size={12}>
          <Form.Item name="viewport_width" label="Width" style={{ marginBottom: 8 }}>
            <InputNumber
              min={800}
              max={3840}
              style={{ width: 120 }}
              onChange={() => form.setFieldsValue({ resolution_preset: "custom" })}
            />
          </Form.Item>
          <span style={{ color: "#6b6b7e", marginTop: 28, display: "inline-block" }}>×</span>
          <Form.Item name="viewport_height" label="Height" style={{ marginBottom: 8 }}>
            <InputNumber
              min={600}
              max={2160}
              style={{ width: 120 }}
              onChange={() => form.setFieldsValue({ resolution_preset: "custom" })}
            />
          </Form.Item>
        </Space>

        {/* -------- Tags -------- */}
        <Form.Item name="tags" label="Tags">
          <Select
            mode="tags"
            placeholder="Add tags..."
            options={existingTags.map((t) => ({ value: t, label: t }))}
            tokenSeparators={[","]}
          />
        </Form.Item>

        {/* -------- Note -------- */}
        <Form.Item name="note" label="Note">
          <Input.TextArea rows={3} placeholder="Optional note..." />
        </Form.Item>
      </Form>

      {/* -------- Info when editing -------- */}
      {isEdit && profile && (
        <>
          <Divider
            orientation="left"
            plain
            style={{ borderColor: "#2a2a40" }}
          >
            Info
          </Divider>
          <Descriptions
            size="small"
            column={1}
            labelStyle={{ color: "#6b6b7e" }}
            contentStyle={{ color: "#b0b0c0" }}
          >
            <Descriptions.Item label="Created">
              {profile.created_at
                ? new Date(profile.created_at).toLocaleString()
                : "\u2014"}
            </Descriptions.Item>
            <Descriptions.Item label="Last Used">
              {profile.last_used
                ? new Date(profile.last_used).toLocaleString()
                : "Never"}
            </Descriptions.Item>
            <Descriptions.Item label="Use Count">
              {profile.use_count ?? 0}
            </Descriptions.Item>
          </Descriptions>

          {/* -------- History -------- */}
          {history.length > 0 && (
            <>
              <Divider
                orientation="left"
                plain
                style={{ borderColor: "#2a2a40" }}
              >
                History ({history.length})
              </Divider>
              <div style={{ maxHeight: 200, overflowY: "auto", paddingLeft: 4 }}>
                <Timeline
                  items={[...history].reverse().slice(0, 50).map((h) => ({
                    color: h.action === "opened" ? "#22c55e" : "#6b6b7e",
                    dot: h.action === "opened" ? (
                      <PlayCircleOutlined style={{ fontSize: 14 }} />
                    ) : (
                      <PauseCircleOutlined style={{ fontSize: 14 }} />
                    ),
                    children: (
                      <span style={{ color: "#8b8b9e", fontSize: 12 }}>
                        <span style={{ color: h.action === "opened" ? "#22c55e" : "#b0b0c0" }}>
                          {h.action === "opened" ? "Started" : "Stopped"}
                        </span>
                        {" — "}
                        {new Date(h.timestamp).toLocaleString()}
                      </span>
                    ),
                  }))}
                />
              </div>
            </>
          )}
        </>
      )}
    </Modal>
  );
}