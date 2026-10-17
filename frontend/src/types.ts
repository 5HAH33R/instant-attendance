export interface ComponentAttendance {
  present: number;
  held: number;
  percentage: number;
}

export interface CourseAttendance {
  course_code: string;
  course_name: string;
  section: string;
  theory: ComponentAttendance;
  practical: ComponentAttendance;
  total_classes: number;
  attended_classes: number;
  percentage: number;
  classes_to_skip: number;
  theory_skip: number;
  practical_skip: number;
  status: "safe" | "warning" | "danger";
}

export interface OverallStats {
  total_classes: number;
  attended_classes: number;
  percentage: number;
  classes_to_skip: number;
  status: "safe" | "warning" | "danger";
}

export interface AttendanceStats {
  courses: CourseAttendance[];
  overall: OverallStats;
  /** Attendance PDF bytes (base64) shipped with the stats for instant PDF tab + refresh restore. */
  pdf_base64?: string;
  /** Download filename derived server-side from the PDF, e.g. "Ali(22B-CS-123)-attendance-2026-10-17.pdf". */
  pdf_filename?: string;
}
