import { useEffect, useRef, useCallback } from "react";
import { api } from "../api";

export function useSSE(jobId, onEvent) {
  const eventSourceRef = useRef(null);
  const onEventRef = useRef(onEvent);
  onEventRef.current = onEvent;

  const connect = useCallback(() => {
    if (!jobId) return;
    if (eventSourceRef.current) {
      eventSourceRef.current.close();
    }

    const es = new EventSource(api.streamUrl(jobId));
    eventSourceRef.current = es;

    // Issue 4: 初始状态快照（重连后补课）
    es.addEventListener("initial_state", (e) => {
      try {
        const data = JSON.parse(e.data);
        onEventRef.current?.("initial_state", data);
      } catch (_) {}
    });

    es.addEventListener("progress", (e) => {
      try {
        const data = JSON.parse(e.data);
        onEventRef.current?.("progress", data);
      } catch (_) {}
    });

    es.addEventListener("token", (e) => {
      try {
        const data = JSON.parse(e.data);
        onEventRef.current?.("token", data);
      } catch (_) {}
    });

    es.addEventListener("chapter_complete", (e) => {
      try {
        const data = JSON.parse(e.data);
        onEventRef.current?.("chapter_complete", data);
      } catch (_) {}
    });

    es.addEventListener("batch_complete", (e) => {
      try {
        const data = JSON.parse(e.data);
        onEventRef.current?.("batch_complete", data);
      } catch (_) {}
    });

    es.addEventListener("job_complete", (e) => {
      try {
        const data = JSON.parse(e.data);
        onEventRef.current?.("job_complete", data);
      } catch (_) {}
      es.close();
    });

    es.addEventListener("quality_issue", (e) => {
      try {
        const data = JSON.parse(e.data);
        onEventRef.current?.("quality_issue", data);
      } catch (_) {}
    });

    es.addEventListener("error", (e) => {
      try {
        const data = JSON.parse(e.data);
        onEventRef.current?.("error", data);
      } catch (_) {}
    });

    es.onerror = () => {
      es.close();
      setTimeout(connect, 3000);
    };
  }, [jobId]);

  useEffect(() => {
    connect();
    return () => {
      if (eventSourceRef.current) {
        eventSourceRef.current.close();
      }
    };
  }, [connect]);

  return { reconnect: connect };
}