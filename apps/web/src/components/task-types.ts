import type { Matter } from "@/lib/types";

export type TaskState = "open" | "in_progress" | "done" | "cancelled";

export type MatterTask = {
  id: string;
  title: string;
  description?: string;
  state: TaskState;
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
