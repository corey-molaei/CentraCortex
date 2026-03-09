function inferApiBaseUrlFromWindow(): string | null {
  if (typeof window === "undefined") {
    return null;
  }

  const { protocol, host, hostname } = window.location;

  if (host === "localhost:5173" || host === "127.0.0.1:5173" || host === "localhost:1455" || host === "127.0.0.1:1455") {
    return "http://localhost:8000";
  }

  if (hostname.includes("centracortex-ui-") && hostname.endsWith(".run.app")) {
    return `${protocol}//${host.replace("centracortex-ui-", "centracortex-")}`;
  }

  return `${protocol}//${host}`;
}

const configuredApiBaseUrl = import.meta.env.VITE_API_BASE_URL;
const inferredApiBaseUrl = inferApiBaseUrlFromWindow();

export const API_BASE_URL = (configuredApiBaseUrl || inferredApiBaseUrl || "http://localhost:8000").replace(/\/+$/, "");
