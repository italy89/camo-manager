import { Form, Input, InputNumber, Select, Button, message } from "antd";
import { SafetyCertificateOutlined } from "@ant-design/icons";

const { Option } = Select;

/**
 * Reusable proxy form fields.
 *
 * Must be rendered inside an Ant Design <Form>.
 * Field names: proxy_type, proxy_host, proxy_port, proxy_user, proxy_pass
 */
export default function ProxyEditor() {
  const handleCheckProxy = () => {
    message.info("Proxy format looks OK (connectivity check coming soon)");
  };

  return (
    <>
      <Form.Item name="proxy_type" label="Proxy Type" initialValue="none">
        <Select>
          <Option value="none">No Proxy</Option>
          <Option value="http">HTTP</Option>
          <Option value="socks5">SOCKS5</Option>
        </Select>
      </Form.Item>

      <Form.Item
        noStyle
        shouldUpdate={(prev, cur) => prev.proxy_type !== cur.proxy_type}
      >
        {({ getFieldValue }) => {
          const proxyType = getFieldValue("proxy_type");
          if (proxyType === "none") return null;

          return (
            <>
              <Form.Item
                name="proxy_host"
                label="Host"
                rules={[
                  { required: true, message: "Proxy host is required" },
                ]}
              >
                <Input placeholder="192.168.1.1 or proxy.example.com" />
              </Form.Item>

              <Form.Item
                name="proxy_port"
                label="Port"
                rules={[
                  { required: true, message: "Proxy port is required" },
                ]}
              >
                <InputNumber
                  min={1}
                  max={65535}
                  placeholder="1080"
                  style={{ width: "100%" }}
                />
              </Form.Item>

              <Form.Item name="proxy_user" label="Username">
                <Input placeholder="(optional)" />
              </Form.Item>

              <Form.Item name="proxy_pass" label="Password">
                <Input.Password placeholder="(optional)" />
              </Form.Item>

              <Form.Item>
                <Button
                  icon={<SafetyCertificateOutlined />}
                  onClick={handleCheckProxy}
                  size="small"
                >
                  Check Proxy
                </Button>
              </Form.Item>
            </>
          );
        }}
      </Form.Item>
    </>
  );
}
