// Options page: profile name + pairing token + port, saved to chrome.storage.local.
const form = document.getElementById("form") as HTMLFormElement;
const statusLine = document.getElementById("status") as HTMLParagraphElement;
const field = (id: string) => document.getElementById(id) as HTMLInputElement;

const LABEL: Record<string, string> = {
  connected: "Connected to Clipper.",
  connecting: "Connecting…",
  idle: "Not connected. Is Clipper running?",
  "bad-token": "The pairing token was refused.",
  replaced: "Another window of this profile is connected.",
  protocol: "Update needed: this Companion and Clipper speak different protocol versions.",
};

async function refresh(): Promise<void> {
  const s = (await chrome.runtime.sendMessage({ type: "clipper.status" })) as { state: string; detail?: string } | undefined;
  statusLine.textContent = s ? `${LABEL[s.state] ?? s.state}${s.detail && s.state !== "connected" ? ` ${s.detail}` : ""}` : "";
}

void chrome.storage.local.get(["profile", "token", "port"]).then((c) => {
  field("profile").value = (c["profile"] as string | undefined) ?? "main";
  field("token").value = (c["token"] as string | undefined) ?? "";
  field("port").value = String(c["port"] ?? 8766);
  void refresh();
});

form.addEventListener("submit", (e) => {
  e.preventDefault();
  void chrome.storage.local
    .set({ profile: field("profile").value.trim() || "main", token: field("token").value.trim(), port: Number(field("port").value) || 8766 })
    .then(() => setTimeout(() => void refresh(), 800));
});
setInterval(() => void refresh(), 3000);
export {};
