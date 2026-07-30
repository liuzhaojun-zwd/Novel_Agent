import { useEffect, useRef, useCallback } from "react";
import { api } from "../api";

const STREAM_EVENTS = [
  "initial_state", "progress", "token",
  "scene_plan", "scene_progress", "scene_complete", "control_state",
  "chapter_complete", "batch_complete", "job_complete", "quality_issue",
  "memory_updated", "memory_warning",
  "outline_progress", "outline_token", "outline_done", "outline_error",
];

export function useSSE(jobId, onEvent) {
  const eventSourceRef = useRef(null);
  const reconnectTimerRef = useRef(null);
  const connectRef = useRef(null);
  const onEventRef = useRef(onEvent);

  useEffect(() => {
    onEventRef.current = onEvent;
  }, [onEvent]);

  const connect = useCallback(() => {
    if (!jobId) return;
    if (reconnectTimerRef.current) {
      window.clearTimeout(reconnectTimerRef.current);
      reconnectTimerRef.current = null;
    }
    eventSourceRef.current?.close();

    const eventSource = new EventSource(api.streamUrl(jobId));
    eventSourceRef.current = eventSource;

    STREAM_EVENTS.forEach((eventName) => {
      eventSource.addEventListener(eventName, (event) => {
        try {
          const data = JSON.parse(event.data);
          onEventRef.current?.(eventName, data);
          if (eventName === "job_complete") eventSource.close();
        } catch {
          // 忽略无法解析的单个事件，不中断后续流。
        }
      });
    });

    eventSource.onerror = () => {
      eventSource.close();
      reconnectTimerRef.current = window.setTimeout(
        () => connectRef.current?.(),
        3000,
      );
    };
  }, [jobId]);

  useEffect(() => {
    connectRef.current = connect;
    connect();
    return () => {
      if (reconnectTimerRef.current) {
        window.clearTimeout(reconnectTimerRef.current);
        reconnectTimerRef.current = null;
      }
      eventSourceRef.current?.close();
      eventSourceRef.current = null;
      connectRef.current = null;
    };
  }, [connect]);

  return { reconnect: connect };
}
