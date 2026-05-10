let ws: WebSocket | null = null;

export function connectWS(roomId: string, onMessage: (data: unknown) => void) {
  const url = `${location.protocol === "https:" ? "wss" : "ws"}://${location.host}/ws/${roomId}`;
  ws = new WebSocket(url);
  ws.onmessage = (e) => onMessage(JSON.parse(e.data));
  ws.onclose = () => setTimeout(() => connectWS(roomId, onMessage), 3000);
  return ws;
}

export function sendCommand(command: object) {
  if (ws?.readyState === WebSocket.OPEN) {
    ws.send(JSON.stringify(command));
  }
}
