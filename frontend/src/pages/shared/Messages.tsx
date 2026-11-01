import { useEffect, useRef, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useSearchParams } from "react-router-dom";
import { ArrowLeft, Lock, RefreshCw, Send } from "lucide-react";

import { cn, errorMessage, formatDateTime, timeAgo } from "@/lib/utils";
import { Avatar, Button, Card, EmptyState, PageLoader } from "@/components/ui";
import { conversationsApi } from "@/api/social";
import { getAccessToken } from "@/api/client";
import { useAuthStore } from "@/stores/auth";
import { toast } from "@/stores/toast";
import { wsService } from "@/services/websocket";
import { CHAT_WS_EVENTS, WS_EVENTS } from "@/lib/constants";
import type { Conversation } from "@/types";

interface ChatFrame {
  event: string;
  data?: Record<string, unknown>;
}

function chatSocketUrl(taskId: string, token: string): string {
  const protocol = window.location.protocol === "https:" ? "wss:" : "ws:";
  return `${protocol}//${window.location.host}/ws/chat/${taskId}?token=${encodeURIComponent(token)}`;
}

export default function Messages() {
  const user = useAuthStore((s) => s.user);
  const queryClient = useQueryClient();
  const [searchParams, setSearchParams] = useSearchParams();
  const activeId = searchParams.get("c");
  const [draft, setDraft] = useState("");
  const [chatClosed, setChatClosed] = useState(false);
  const [socketReady, setSocketReady] = useState(false);
  const bottomRef = useRef<HTMLDivElement | null>(null);
  const socketRef = useRef<WebSocket | null>(null);

  const conversationsQuery = useQuery({
    queryKey: ["conversations"],
    queryFn: () => conversationsApi.list(),
    refetchInterval: 20_000,
  });

  const active: Conversation | undefined = (conversationsQuery.data ?? []).find((c) => c.id === activeId);
  const chatOpen = Boolean(active?.chat_open) && !chatClosed;

  const messagesQuery = useQuery({
    queryKey: ["messages", activeId],
    queryFn: () => conversationsApi.messages(activeId!, 1, 100),
    enabled: !!activeId,
    refetchInterval: 10_000,
  });

  useEffect(() => {
    setChatClosed(false);
    setSocketReady(false);
    setDraft("");
  }, [activeId]);

  // Global socket (notifications, task updates) also carries chat messages
  // for REST sends; keep the open thread fresh.
  useEffect(() => {
    const off = wsService.on(WS_EVENTS.MESSAGE, () => {
      void queryClient.invalidateQueries({ queryKey: ["conversations"] });
      if (activeId) void queryClient.invalidateQueries({ queryKey: ["messages", activeId] });
    });
    return off;
  }, [activeId, queryClient]);

  // Task-scoped chat socket: authoritative for send, close notices and reads.
  useEffect(() => {
    const taskId = active?.task_id;
    if (!activeId || !taskId || !active?.chat_open || chatClosed) {
      setSocketReady(false);
      return;
    }
    const token = getAccessToken();
    if (!token) return;

    const socket = new WebSocket(chatSocketUrl(taskId, token));
    socketRef.current = socket;

    const markRead = () => {
      if (socket.readyState === WebSocket.OPEN && !chatClosed) {
        socket.send(JSON.stringify({ event: "read" }));
      }
    };

    socket.onopen = () => {
      if (socketRef.current === socket) setSocketReady(true);
    };

    socket.onmessage = (raw) => {
      let frame: ChatFrame;
      try {
        frame = JSON.parse(String(raw.data)) as ChatFrame;
      } catch {
        return;
      }
      const data = frame.data ?? {};
      switch (frame.event) {
        case CHAT_WS_EVENTS.READY:
          markRead();
          break;
        case CHAT_WS_EVENTS.CLOSED:
          setChatClosed(true);
          setSocketReady(false);
          void queryClient.invalidateQueries({ queryKey: ["conversations"] });
          break;
        case CHAT_WS_EVENTS.MESSAGE_SENT:
          void queryClient.invalidateQueries({ queryKey: ["messages", activeId] });
          void queryClient.invalidateQueries({ queryKey: ["conversations"] });
          break;
        case "message":
          void queryClient.invalidateQueries({ queryKey: ["messages", activeId] });
          void queryClient.invalidateQueries({ queryKey: ["conversations"] });
          markRead();
          break;
        case CHAT_WS_EVENTS.READ:
          void queryClient.invalidateQueries({ queryKey: ["conversations"] });
          break;
        case CHAT_WS_EVENTS.ERROR:
          toast.error(String(data.message ?? "Message could not be sent."));
          break;
        default:
          break;
      }
    };

    socket.onclose = (event) => {
      if (socketRef.current !== socket) return;
      socketRef.current = null;
      setSocketReady(false);
      if (event.code === 4409) {
        setChatClosed(true);
        void queryClient.invalidateQueries({ queryKey: ["conversations"] });
      }
    };

    const heartbeat = window.setInterval(() => {
      if (socket.readyState === WebSocket.OPEN) {
        socket.send(JSON.stringify({ event: "ping" }));
      }
    }, 25_000);

    return () => {
      window.clearInterval(heartbeat);
      socketRef.current = null;
      socket.close();
    };
  }, [activeId, active?.task_id, active?.chat_open, chatClosed, queryClient]);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messagesQuery.data?.items.length]);

  useEffect(() => {
    const socket = socketRef.current;
    if (socket?.readyState === WebSocket.OPEN && chatOpen) {
      socket.send(JSON.stringify({ event: "read" }));
      queryClient.setQueryData<Conversation[]>(["conversations"], (old) =>
        old?.map((c) => (c.id === activeId ? { ...c, unread_count: 0 } : c))
      );
    }
  }, [messagesQuery.data?.items.length, activeId, chatOpen, queryClient]);

  const sendMutation = useMutation({
    mutationFn: (body: string) => conversationsApi.send(activeId!, body),
    onSuccess: () => {
      setDraft("");
      void queryClient.invalidateQueries({ queryKey: ["messages", activeId] });
      void queryClient.invalidateQueries({ queryKey: ["conversations"] });
    },
    onError: (e) => {
      toast.error(errorMessage(e));
      void queryClient.invalidateQueries({ queryKey: ["conversations"] });
    },
  });

  const send = () => {
    const body = draft.trim();
    if (!body || !chatOpen) return;
    const socket = socketRef.current;
    if (socket?.readyState === WebSocket.OPEN) {
      socket.send(JSON.stringify({ event: "send_message", data: { body } }));
      setDraft("");
    } else {
      sendMutation.mutate(body);
    }
  };

  if (conversationsQuery.isLoading) return <PageLoader label="Loading conversations…" />;

  const conversations = conversationsQuery.data ?? [];
  const messages = messagesQuery.data?.items ?? [];

  return (
    <div className="space-y-5">
      <div>
        <h1 className="text-xl font-bold text-slate-900">Messages</h1>
        <p className="mt-0.5 text-sm text-slate-500">
          Task-scoped chat only — phone numbers stay private and messages never leave TaskFlex.
        </p>
      </div>

      <div className="grid gap-5 lg:grid-cols-3">
        {/* Conversation list */}
        <div className={cn("space-y-3", activeId && "hidden lg:block")}>
          {conversations.length === 0 ? (
            <EmptyState
              icon="💬"
              title="No conversations yet"
              description="A private chat opens automatically once a runner is assigned to your task."
            />
          ) : (
            conversations.map((c) => (
              <button
                key={c.id}
                type="button"
                onClick={() => setSearchParams({ c: c.id })}
                className={cn(
                  "card flex w-full items-center gap-3 p-3.5 text-left transition",
                  c.id === activeId ? "border-primary-400 ring-1 ring-primary-300" : "hover:border-primary-300"
                )}
              >
                <Avatar name={c.counterpart_name ?? "User"} url={c.counterpart_avatar} />
                <div className="min-w-0 flex-1">
                  <div className="flex items-center justify-between gap-2">
                    <p className="truncate text-sm font-semibold text-slate-900">
                      {c.counterpart_name ?? "TaskFlex user"}
                    </p>
                    {c.last_message_at && (
                      <span className="shrink-0 text-[11px] text-slate-400">{timeAgo(c.last_message_at)}</span>
                    )}
                  </div>
                  <div className="flex items-center gap-1.5">
                    {c.task_title && <p className="truncate text-[11px] text-primary-600">{c.task_title}</p>}
                    {!c.chat_open && <Lock className="h-3 w-3 shrink-0 text-slate-400" aria-label="Conversation closed" />}
                  </div>
                  <p className="truncate text-xs text-slate-500">
                    {c.chat_open ? (c.unread_count > 0 ? "New messages waiting" : "Tap to open conversation") : "Read-only — conversation closed"}
                  </p>
                </div>
                {c.unread_count > 0 && (
                  <span className="flex h-5 min-w-5 shrink-0 items-center justify-center rounded-full bg-primary-600 px-1.5 text-[11px] font-bold text-white">
                    {c.unread_count}
                  </span>
                )}
              </button>
            ))
          )}
        </div>

        {/* Chat pane */}
        <div className={cn(!activeId && "hidden lg:block", "lg:col-span-2")}>
          {!activeId ? (
            <EmptyState icon="✉️" title="Select a conversation" description="Pick a chat on the left to see the full history." />
          ) : !active ? (
            <PageLoader label="Opening conversation…" />
          ) : (
            <Card className="flex h-[70vh] flex-col p-0">
              <div className="flex items-center gap-3 border-b border-slate-100 p-4">
                <button
                  type="button"
                  className="rounded-lg p-1.5 text-slate-400 hover:bg-slate-100 lg:hidden"
                  onClick={() => setSearchParams({})}
                  aria-label="Back to conversations"
                >
                  <ArrowLeft className="h-4 w-4" aria-hidden />
                </button>
                <Avatar name={active.counterpart_name} url={active.counterpart_avatar} size="sm" />
                <div className="min-w-0 flex-1">
                  <p className="truncate text-sm font-semibold text-slate-900">
                    {active.counterpart_name ?? "TaskFlex user"}
                  </p>
                  {active.task_title && <p className="truncate text-xs text-slate-400">Regarding: {active.task_title}</p>}
                </div>
                {chatOpen && active.closes_at && (
                  <span className="hidden shrink-0 text-[11px] text-slate-400 sm:block">
                    Open until {formatDateTime(active.closes_at)}
                  </span>
                )}
                {!chatOpen && (
                  <span className="flex shrink-0 items-center gap-1 rounded-full bg-slate-100 px-2 py-1 text-[11px] font-medium text-slate-600">
                    <Lock className="h-3 w-3" aria-hidden /> Closed
                  </span>
                )}
              </div>

              {!chatOpen && (
                <div className="border-b border-amber-100 bg-amber-50 px-4 py-2 text-xs text-amber-800">
                  This conversation is read-only. Task chats close automatically 24 hours after the task is completed
                  or cancelled, and the history stays available to both participants.
                </div>
              )}

              <div className="flex-1 space-y-2 overflow-y-auto p-4">
                {messagesQuery.isLoading ? (
                  <p className="text-center text-sm text-slate-400">Loading messages…</p>
                ) : messages.length === 0 ? (
                  <p className="text-center text-sm text-slate-400">No messages yet — say hello!</p>
                ) : (
                  messages.map((m) => {
                    const mine = m.sender_id === user?.id;
                    return (
                      <div key={m.id} className={cn("flex", mine ? "justify-end" : "justify-start")}>
                        <div
                          className={cn(
                            "max-w-[80%] rounded-2xl px-3.5 py-2 text-sm",
                            mine ? "bg-primary-600 text-white" : "bg-slate-100 text-slate-800"
                          )}
                        >
                          <p className="whitespace-pre-line break-words">{m.body}</p>
                          <p className={cn("mt-1 text-[10px]", mine ? "text-primary-200" : "text-slate-400")}>
                            {formatDateTime(m.created_at)}
                          </p>
                        </div>
                      </div>
                    );
                  })
                )}
                <div ref={bottomRef} />
              </div>

              {chatOpen && !socketReady && (
                <div className="flex items-center gap-1.5 border-t border-slate-100 px-4 py-1.5 text-[11px] text-slate-400">
                  <RefreshCw className="h-3 w-3 animate-spin" aria-hidden /> Connecting live chat — sends fall back to a
                  secure REST channel.
                </div>
              )}

              <form
                className="flex items-center gap-2 border-t border-slate-100 p-3"
                onSubmit={(e) => {
                  e.preventDefault();
                  send();
                }}
              >
                <input
                  className="input flex-1"
                  placeholder={chatOpen ? "Type a message…" : "This conversation is closed"}
                  value={draft}
                  maxLength={2000}
                  disabled={!chatOpen}
                  onChange={(e) => setDraft(e.target.value)}
                />
                <Button
                  type="submit"
                  loading={sendMutation.isPending}
                  disabled={!chatOpen || draft.trim().length === 0}
                  aria-label="Send message"
                >
                  <Send className="h-4 w-4" aria-hidden />
                </Button>
              </form>
            </Card>
          )}
        </div>
      </div>
    </div>
  );
}
