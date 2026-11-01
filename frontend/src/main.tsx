import React from "react";
import ReactDOM from "react-dom/client";
import { BrowserRouter } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import App from "./App";
import "./index.css";
import { wsService } from "./services/websocket";
import { useAuthStore } from "./stores/auth";
import { Toaster } from "./components/Toaster";
import { useNotificationsReady } from "./stores/notifications";

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      retry: 1,
      refetchOnWindowFocus: false,
      staleTime: 15_000,
    },
  },
});

function SessionBridge() {
  const user = useAuthStore((s) => s.user);

  React.useEffect(() => {
    if (!user) {
      wsService.disconnect();
      return;
    }
    wsService.connect();
  }, [user]);

  React.useEffect(() => {
    const onExpired = () => {
      useAuthStore.getState().logout();
      queryClient.clear();
    };
    window.addEventListener("taskflex:session-expired", onExpired);
    return () => window.removeEventListener("taskflex:session-expired", onExpired);
  }, []);

  useNotificationsReady();
  return null;
}

ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <QueryClientProvider client={queryClient}>
      <BrowserRouter>
        <SessionBridge />
        <App />
        <Toaster />
      </BrowserRouter>
    </QueryClientProvider>
  </React.StrictMode>
);
