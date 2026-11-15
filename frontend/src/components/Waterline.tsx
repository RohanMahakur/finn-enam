// The Waterline: one control for "how much do I want to see?". Everything scoring below the
// line sinks. Drag the wave (or use the slider) to raise or lower the noise floor.
export function Waterline({ value, onChange, above, below }: { value: number; onChange: (v: number) => void; above: number; below: number }) {
  return (
    <div className="waterline">
      <svg viewBox="0 0 400 24" preserveAspectRatio="none" className="wave" aria-hidden>
        <path d="M0 12 Q 25 2 50 12 T 100 12 T 150 12 T 200 12 T 250 12 T 300 12 T 350 12 T 400 12 V24 H0Z" />
      </svg>
      <div className="wl-row">
        <span className="wl-count">{above} above</span>
        <input aria-label="Noise floor" type="range" min={0} max={90} step={5} value={value}
          onChange={(e) => onChange(Number(e.target.value))} />
        <span className="wl-count dim">{below} below</span>
      </div>
      <div className="wl-cap">noise floor <b>{value}</b> — drag to let more in or keep more out</div>
    </div>
  );
}
