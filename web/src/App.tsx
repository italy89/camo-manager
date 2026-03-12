import { ConfigProvider, Layout, theme } from "antd";
import ProfileList from "./pages/ProfileList";
import "./App.css";

const { Header, Content } = Layout;

function App() {
  return (
    <ConfigProvider
      theme={{
        algorithm: theme.darkAlgorithm,
        token: {
          colorPrimary: "#7c3aed",
          colorBgContainer: "#111118",
          colorBgElevated: "#151520",
          colorBgLayout: "#0a0a0f",
          colorBorder: "#1f1f2e",
          colorBorderSecondary: "#1a1a28",
          borderRadius: 8,
          fontFamily:
            '-apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif',
        },
        components: {
          Table: {
            headerBg: "#161622",
            headerColor: "#8b8b9e",
            rowHoverBg: "#1a1a2e",
            rowSelectedBg: "#1a1a35",
            rowSelectedHoverBg: "#222240",
            borderColor: "#1a1a28",
            colorBgContainer: "#111118",
          },
          Modal: {
            contentBg: "#151520",
            headerBg: "#151520",
            titleColor: "#e0e0e0",
          },
          Input: {
            colorBgContainer: "#0e0e18",
            colorBorder: "#2a2a40",
            activeBorderColor: "#7c3aed",
            hoverBorderColor: "#5a2dbd",
          },
          Select: {
            colorBgContainer: "#0e0e18",
            colorBorder: "#2a2a40",
            optionSelectedBg: "#1a1a35",
          },
          Button: {
            defaultBg: "#1a1a2e",
            defaultBorderColor: "#2a2a40",
            defaultColor: "#c0c0d0",
          },
          Tag: {
            defaultBg: "#1a1a2e",
            defaultColor: "#c0c0d0",
          },
        },
      }}
    >
      <Layout style={{ minHeight: "100vh", background: "#0a0a0f" }}>
        <Header className="app-header">
          <div className="app-logo">
            <span className="app-logo-icon">🦊</span>
            <span className="app-logo-text">CamoManager</span>
          </div>
        </Header>
        <Content className="app-content">
          <ProfileList />
        </Content>
      </Layout>
    </ConfigProvider>
  );
}

export default App;
