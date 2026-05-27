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
}
