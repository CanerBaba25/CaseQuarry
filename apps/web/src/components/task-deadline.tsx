import { uiText } from "@/lib/i18n";
import { date } from "@/lib/api";
import { Badge } from "./ui";

export function TaskDeadline({
  value,
  today,
  complete = false,
}: {
  value: string | null;
  today: string;
  complete?: boolean;
}) {
  if (!value) return <Badge value="No due date" />;
  const overdue = !complete && value < today;
  const dueToday = !complete && value === today;
  return (
    <span title={uiText("Due {0}", { "0": date(value) })}>
      <Badge
        value={overdue ? "Overdue" : dueToday ? "Due today" : "Due date"}
        text={
          overdue
            ? `${uiText("Overdue")} · ${date(value)}`
            : dueToday
              ? uiText("Due today")
              : uiText("Due {0}", { "0": date(value) })
        }
        tone={overdue ? "red" : dueToday ? "amber" : "neutral"}
      />
    </span>
  );
}
