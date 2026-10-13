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
    <span title={`Due ${date(value)}`}>
      <Badge
        value={
          overdue
            ? `Overdue · ${date(value)}`
            : dueToday
              ? "Due today"
              : `Due ${date(value)}`
        }
        tone={overdue ? "red" : dueToday ? "amber" : "neutral"}
      />
    </span>
  );
}
