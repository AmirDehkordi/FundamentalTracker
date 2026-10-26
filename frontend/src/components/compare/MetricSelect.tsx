import {
  Select,
  SelectContent,
  SelectGroup,
  SelectItem,
  SelectLabel,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { COMPARE_METRIC_GROUPS } from "@/lib/metrics";

/** Grouped selector over the backend's comparable metrics. */
export function MetricSelect({
  value,
  onChange,
}: {
  value: string;
  onChange: (value: string) => void;
}) {
  return (
    <Select value={value} onValueChange={onChange}>
      <SelectTrigger className="w-56" aria-label="Comparison metric">
        <SelectValue />
      </SelectTrigger>
      <SelectContent>
        {COMPARE_METRIC_GROUPS.map((group) => (
          <SelectGroup key={group.label}>
            <SelectLabel className="text-fg-3">{group.label}</SelectLabel>
            {group.options.map((o) => (
              <SelectItem key={o.value} value={o.value}>
                {o.label}
              </SelectItem>
            ))}
          </SelectGroup>
        ))}
      </SelectContent>
    </Select>
  );
}
