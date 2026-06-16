import type { SignalChip } from "@/lib/signals";
import { biasIcon } from "@/lib/signals";

export default function SignalChips({ signals }: { signals: SignalChip[] }) {
  if (signals.length === 0) return null;

  return (
    <div className="signal-chips">
      {signals.map((s) => (
        <span
          key={s.name}
          className={`chip ${s.bias}`}
          title={s.label || undefined}
        >
          {biasIcon(s.bias)} {s.name}
        </span>
      ))}
    </div>
  );
}
