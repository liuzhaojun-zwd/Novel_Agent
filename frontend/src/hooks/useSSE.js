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

    es.addEventListener("progress", (e) => {
      const data = JSON.parse(e.data);
      onEventRef.current?.("progress", data);
    });

    es.addEventListener("chapter_complete", (e) => {
      const data = JSON.parse(e.data);
      onEventRef.current?.("chapter_complete", data);
    });

    es.addEventListener("job_complete", (e) => {
      const data = JSON.parse(e.data);
      onEventRef.current?.("job_complete", data);
      es.close();
    });

    es.addEventListener("error", (e) => {
      const data = JSON.parse(e.data);
      onEventRef.current?.("error", data);
    });

    es.onerror = () => {
      // 自动重连
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