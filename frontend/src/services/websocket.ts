import type { WsEvent } from "@/types";
import { getAccessToken } from "@/api/client";

type Listener = (event: WsEvent) => void;

const MAX_BACKOFF_MS = 30000;

class WebSocketService {
  private socket: WebSocket | null = null;
  private listeners = new Map<string, Set<Listener>>();
  private anyListeners = new Set<Listener>();
  private reconnectAttempts = 0;
  private reconnectTimer: ReturnType<typeof setTimeout> | null = null;
  private heartbeatTimer: ReturnType<typeof setInterval> | null = null;
  private intentionallyClosed = false;

  connect(): void {
    if (this.socket && (this.socket.readyState === WebSocket.OPEN || this.socket.readyState === WebSocket.CONNECTING)) {
      return;
    }
    const token = getAccessToken();
    if (!token) return;

    const protocol = window.location.protocol === "https:" ? "wss:" : "ws:";
    const url = `${protocol}//${window.location.host}/ws?token=${encodeURIComponent(token)}`;
    this.intentionallyClosed = false;
    this.socket = new WebSocket(url);

    this.socket.onopen = () => {
      this.reconnectAttempts = 0;
      this.startHeartbeat();
    };

    this.socket.onmessage = (raw) => {
      try {
        const event = JSON.parse(raw.data as string) as WsEvent;
        if (event.event === "pong") return;
        this.listeners.get(event.event)?.forEach((fn) => fn(event));
        this.anyListeners.forEach((fn) => fn(event));
      } catch {
        // ignore malformed frames
      }
    };

    this.socket.onclose = (e) => {
      this.stopHeartbeat();
      if (this.intentionallyClosed || e.code === 4401 || e.code === 4403) return;
      this.scheduleReconnect();
    };

    this.socket.onerror = () => {
      this.socket?.close();
    };
  }

  private scheduleReconnect(): void {
    if (this.reconnectTimer) return;
    const delay = Math.min(1000 * 2 ** this.reconnectAttempts, MAX_BACKOFF_MS);
    this.reconnectAttempts += 1;
    this.reconnectTimer = setTimeout(() => {
      this.reconnectTimer = null;
      this.connect();
    }, delay);
  }

  private startHeartbeat(): void {
    this.stopHeartbeat();
    this.heartbeatTimer = setInterval(() => {
      if (this.socket?.readyState === WebSocket.OPEN) {
        this.socket.send("ping");
      }
    }, 25000);
  }

  private stopHeartbeat(): void {
    if (this.heartbeatTimer) {
      clearInterval(this.heartbeatTimer);
      this.heartbeatTimer = null;
    }
  }

  disconnect(): void {
    this.intentionallyClosed = true;
    this.stopHeartbeat();
    if (this.reconnectTimer) {
      clearTimeout(this.reconnectTimer);
      this.reconnectTimer = null;
    }
    this.socket?.close();
    this.socket = null;
  }

  on(eventName: string, listener: Listener): () => void {
    if (!this.listeners.has(eventName)) this.listeners.set(eventName, new Set());
    this.listeners.get(eventName)!.add(listener);
    return () => {
      this.listeners.get(eventName)?.delete(listener);
    };
  }

  send(data: unknown): void {
    if (this.socket?.readyState === WebSocket.OPEN) {
      this.socket.send(JSON.stringify(data));
    }
  }

  onAny(listener: Listener): () => void {
    this.anyListeners.add(listener);
    return () => {
      this.anyListeners.delete(listener);
    };
  }
}

export const wsService = new WebSocketService();
