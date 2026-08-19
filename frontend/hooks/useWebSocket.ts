'use client';

import { useEffect, useRef, useCallback, useState } from 'react';

type WSEventHandler = (data: Record<string, unknown>) => void;

interface UseWebSocketOptions {
  onMessage?: (event: string, data: Record<string, unknown>) => void;
  reconnectDelay?: number;
}

export function useWebSocket(options: UseWebSocketOptions = {}) {
  const wsRef = useRef<WebSocket | null>(null);
  const handlersRef = useRef<Map<string, Set<WSEventHandler>>>(new Map());
  const reconnectTimerRef = useRef<NodeJS.Timeout | null>(null);
  const [isConnected, setIsConnected] = useState(false);
  const { onMessage, reconnectDelay = 3000 } = options;

  const connect = useCallback(() => {
    const token = typeof window !== 'undefined' ? localStorage.getItem('auth_token') : null;
    if (!token) return;

    const wsBase = process.env.NEXT_PUBLIC_WS_URL || 'ws://localhost:8000';
    const wsUrl = `${wsBase}/ws/${token}`;

    const ws = new WebSocket(wsUrl);
    wsRef.current = ws;

    ws.onopen = () => {
      setIsConnected(true);
      // Send ping every 25s to keep alive
      const pingInterval = setInterval(() => {
        if (ws.readyState === WebSocket.OPEN) {
          ws.send('ping');
        }
      }, 25000);
      (ws as any)._pingInterval = pingInterval;
    };

    ws.onmessage = (event) => {
      try {
        const { event: eventType, data } = JSON.parse(event.data);
        if (eventType === 'pong') return;

        // Call registered handlers
        const handlers = handlersRef.current.get(eventType);
        if (handlers) {
          handlers.forEach((handler) => handler(data));
        }

        // Call wildcard handler
        const wildcardHandlers = handlersRef.current.get('*');
        if (wildcardHandlers) {
          wildcardHandlers.forEach((handler) => handler({ event: eventType, ...data }));
        }

        onMessage?.(eventType, data);
      } catch (err) {
        // Non-JSON message (like 'pong')
      }
    };

    ws.onclose = () => {
      setIsConnected(false);
      clearInterval((ws as any)._pingInterval);

      // Reconnect
      reconnectTimerRef.current = setTimeout(() => {
        connect();
      }, reconnectDelay);
    };

    ws.onerror = () => {
      ws.close();
    };
  }, [onMessage, reconnectDelay]);

  const disconnect = useCallback(() => {
    if (reconnectTimerRef.current) {
      clearTimeout(reconnectTimerRef.current);
    }
    if (wsRef.current) {
      clearInterval((wsRef.current as any)._pingInterval);
      wsRef.current.close();
      wsRef.current = null;
    }
    setIsConnected(false);
  }, []);

  const on = useCallback((event: string, handler: WSEventHandler) => {
    if (!handlersRef.current.has(event)) {
      handlersRef.current.set(event, new Set());
    }
    handlersRef.current.get(event)!.add(handler);

    return () => {
      handlersRef.current.get(event)?.delete(handler);
    };
  }, []);

  useEffect(() => {
    connect();
    return () => {
      disconnect();
    };
  }, [connect, disconnect]);

  return { isConnected, on, disconnect, reconnect: connect };
}
