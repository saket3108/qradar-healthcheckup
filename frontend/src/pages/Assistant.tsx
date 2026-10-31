import { Bot, Loader2, Send, Sparkles, Trash2, User as UserIcon } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import Markdown from "react-markdown";
import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/primitives";
import { ErrorState, PageHeader } from "@/components/common";
import { useAssessmentCtx } from "@/pages/AssessmentLayout";
import { useAsk, useChat, useClearChat } from "@/lib/queries";
import { cn, errMsg } from "@/lib/utils";

export const SUGGESTIONS = ["Why is health score low?", "Show critical findings.", "Why is EPS high?", "What should customer fix first?", "Explain this notification.", "Summarise the WinCollect situation", "How is performance on the console?"];

export default function Assistant() {
  const { id } = useAssessmentCtx();
  const chat = useChat(id);
  const ask = useAsk(id);
  const clear = useClearChat(id);
  const [text, setText] = useState("");
  const [pending, setPending] = useState<string | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const end = useRef<HTMLDivElement>(null);
  const msgs = chat.data ?? [];

  useEffect(() => { end.current?.scrollIntoView({ behavior: "smooth", block: "end" }); }, [msgs.length, pending]);

  async function send(message: string) {
    const m = message.trim();
    if (!m || ask.isPending) return;
    setErr(null); setPending(m); setText("");
    try { await ask.mutateAsync(m); } catch (e) { setErr(errMsg(e)); setText(m); } finally { setPending(null); }
  }

  return (
    <div className="mx-auto max-w-4xl">
      <PageHeader title="AI Assistant" description="Ask questions about this assessment. Answers are grounded in the uploaded data: scores, findings, notifications, licensing and performance."
        actions={msgs.length > 0 ? <Button variant="outline" size="sm" onClick={() => clear.mutate()} disabled={clear.isPending}><Trash2 />Clear conversation</Button> : undefined} />
      <div className="card-surface flex h-[calc(100vh-290px)] min-h-[460px] flex-col overflow-hidden">
        <div className="flex-1 space-y-5 overflow-y-auto p-5" role="log" aria-live="polite" aria-label="Conversation">
          {chat.error && <ErrorState error={chat.error} retry={() => void chat.refetch()} />}
          {msgs.length === 0 && !pending && (
            <div className="grid h-full place-items-center text-center">
              <div className="max-w-md"><div className="mx-auto mb-3 grid size-12 place-items-center rounded-2xl bg-primary/15 text-primary"><Sparkles className="size-6" /></div>
                <h2 className="font-semibold">Ask anything about this health check</h2><p className="mt-1 text-sm text-muted-foreground">I only answer from the uploaded assessment data, so every answer can be traced back to a finding.</p></div>
            </div>
          )}
          {msgs.map((m, i) => (
            <div key={m.id ?? i} className={cn("flex gap-3", m.role === "user" && "flex-row-reverse")}>
              <div className={cn("grid size-8 shrink-0 place-items-center rounded-full", m.role === "user" ? "bg-accent" : "bg-primary text-primary-foreground")}>{m.role === "user" ? <UserIcon className="size-4" /> : <Bot className="size-4" />}</div>
              <div className={cn("max-w-[85%] rounded-2xl px-4 py-2.5 text-sm leading-relaxed", m.role === "user" ? "rounded-tr-sm bg-primary text-primary-foreground" : "rounded-tl-sm border bg-background/60")}>
                {m.role === "user" ? m.content : <div className="prose-sm space-y-2 [&_li]:ml-4 [&_li]:list-disc [&_ol>li]:list-decimal [&_p]:my-1.5 [&_strong]:font-semibold [&_ul]:my-1.5"><Markdown>{m.content}</Markdown></div>}
              </div>
            </div>
          ))}
          {pending && (<>
            <div className="flex flex-row-reverse gap-3"><div className="grid size-8 shrink-0 place-items-center rounded-full bg-accent"><UserIcon className="size-4" /></div><div className="max-w-[85%] rounded-2xl rounded-tr-sm bg-primary px-4 py-2.5 text-sm text-primary-foreground">{pending}</div></div>
            <div className="flex gap-3" aria-label="Assistant is typing"><div className="grid size-8 shrink-0 place-items-center rounded-full bg-primary text-primary-foreground"><Bot className="size-4" /></div><div className="flex items-center gap-1.5 rounded-2xl border bg-background/60 px-4 py-3">{[0, 1, 2].map((d) => <span key={d} className="size-1.5 animate-pulseDot rounded-full bg-muted-foreground" style={{ animationDelay: `${d * 0.2}s` }} />)}</div></div>
          </>)}
          <div ref={end} />
        </div>
        <div className="border-t bg-background/40 p-3">
          {err && <p role="alert" className="mb-2 text-xs text-sev-critical">{err}</p>}
          <div className="mb-2 flex flex-wrap gap-1.5">{SUGGESTIONS.map((s) => <button key={s} onClick={() => void send(s)} disabled={ask.isPending} className="rounded-full border bg-card px-3 py-1 text-xs text-muted-foreground transition-colors hover:border-primary/50 hover:text-foreground disabled:opacity-50">{s}</button>)}</div>
          <form className="flex items-end gap-2" onSubmit={(e) => { e.preventDefault(); void send(text); }}>
            <Textarea aria-label="Message" rows={1} value={text} onChange={(e) => setText(e.target.value)} placeholder="Ask about findings, EPS, notifications, performance…" className="max-h-32 min-h-[40px] resize-none"
              onKeyDown={(e) => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); void send(text); } }} maxLength={2000} />
            <Button type="submit" size="icon" aria-label="Send message" disabled={!text.trim() || ask.isPending}>{ask.isPending ? <Loader2 className="animate-spin" /> : <Send />}</Button>
          </form>
        </div>
      </div>
    </div>
  );
}
