import type { Matter } from "@/lib/types";

export type TaskState = "open" | "in_progress" | "done" | "cancelled";
export const taskPriorities = ["low", "normal", "high", "urgent"] as const;
export type TaskPriority = (typeof taskPriorities)[number];
export function taskPriorityTone(priority: TaskPriority): string {
  return priority === "urgent"
    ? "red"
    : priority === "high"
      ? "amber"
      : "neutral";
}

export type MatterTask = {
  id: string;
  title: string;
  description?: string;
  state: TaskState;
  priority: TaskPriority;
  assigned_to: string | null;
  due_date: string | null;
  created_by: string;
  created_at: string;
  updated_at: string;
  version: number;
  case_id?: string;
};

export type TaskDetail = MatterTask & {
  case_id: string;
  description: string;
  server_today?: string;
  time_zone?: string;
};

export type TaskMatter = Pick<Matter, "id" | "title" | "role"> &
  Partial<Pick<Matter, "matter_number" | "archived_at">>;
