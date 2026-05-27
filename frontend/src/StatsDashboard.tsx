import type { AttendanceStats, CourseAttendance } from "./types";

const statusColors = {
  safe: "#22c55e",
  warning: "#f59e0b",
  danger: "#ef4444",
};

const statusLabels = {
  safe: "Safe",
  warning: "Warning",
  danger: "Danger",
};

const CourseCard = ({ course }: { course: CourseAttendance }) => {
  const isBelowThreshold = course.classes_to_skip === 0 && course.percentage < 75;
  const hasPractical = course.practical.held > 0;

  return (
    <div className="course-card">
      <div className="course-card-header">
        <div>
          <div className="course-name">{course.course_name}</div>
          <div className="course-code">
            {course.course_code}
            {course.section && ` · Section ${course.section}`}
          </div>
        </div>
        <span
          className={`status-badge ${course.status}`}
          style={{
            background: `${statusColors[course.status]}22`,
            color: statusColors[course.status],
          }}
        >
          {statusLabels[course.status]}
        </span>
      </div>

      {/* Overall Progress */}
      <div className="progress-bar">
        <div
          className="progress-bar-fill"
          style={{
            width: `${Math.min(course.percentage, 100)}%`,
            background: statusColors[course.status],
          }}
        />
      </div>

      <div className="course-stats-row">
        <span className="course-percentage" style={{ color: statusColors[course.status] }}>
          {course.percentage.toFixed(1)}%
        </span>
        <span className="course-classes">
          {course.attended_classes} / {course.total_classes} classes
        </span>
      </div>

      {/* Theory/Practical Breakdown */}
      <div className="component-breakdown">
        <div className="component-row">
          <span className="component-label">Theory</span>
          <div className="component-bar">
            <div
              className="component-bar-fill"
              style={{
                width: `${Math.min(course.theory.percentage, 100)}%`,
                background: course.theory.percentage >= 75 ? statusColors.safe : statusColors.danger,
              }}
            />
          </div>
          <span className="component-stats">
            {course.theory.present}/{course.theory.held}
            <span className="component-pct"> ({course.theory.percentage.toFixed(1)}%)</span>
          </span>
          {course.theory_skip > 0 && (
            <span className="component-skip" style={{ color: statusColors.safe }}>
              +{course.theory_skip}
            </span>
          )}
        </div>

        {hasPractical && (
          <div className="component-row">
            <span className="component-label">Practical</span>
            <div className="component-bar">
              <div
                className="component-bar-fill"
                style={{
                  width: `${Math.min(course.practical.percentage, 100)}%`,
                  background: course.practical.percentage >= 75 ? statusColors.safe : statusColors.danger,
                }}
              />
            </div>
            <span className="component-stats">
              {course.practical.present}/{course.practical.held}
              <span className="component-pct"> ({course.practical.percentage.toFixed(1)}%)</span>
            </span>
            {course.practical_skip > 0 && (
              <span className="component-skip" style={{ color: statusColors.safe }}>
                +{course.practical_skip}
              </span>
            )}
          </div>
        )}
      </div>

      <div className="course-skip-info">
        {isBelowThreshold ? (
          <span style={{ color: statusColors.danger }}>
            You need to attend more classes
          </span>
        ) : course.classes_to_skip > 0 ? (
          <span style={{ color: statusColors.safe }}>
            You can skip {course.classes_to_skip} more class{course.classes_to_skip !== 1 ? "es" : ""}
          </span>
        ) : (
          <span style={{ color: statusColors.warning }}>
            No more classes to skip
          </span>
        )}
      </div>
    </div>
  );
};

const StatsDashboard = ({ stats }: { stats: AttendanceStats }) => {
  const { courses, overall } = stats;

  return (
    <div className="stats-container">
      {/* Overall Summary */}
      <div className="stats-overall">
        <div
          className="overall-percentage"
          style={{ color: statusColors[overall.status] }}
        >
          {overall.percentage.toFixed(1)}%
        </div>
        <div className="overall-label">Overall Attendance</div>
        <div className="overall-detail">
          {overall.attended_classes} of {overall.total_classes} classes attended
        </div>
        <div className="overall-skip">
          {overall.classes_to_skip > 0 ? (
            <span style={{ color: statusColors.safe }}>
              You can skip {overall.classes_to_skip} more class{overall.classes_to_skip !== 1 ? "es" : ""} overall
            </span>
          ) : overall.percentage < 75 ? (
            <span style={{ color: statusColors.danger }}>
              Your attendance is below the 75% threshold
            </span>
          ) : (
            <span style={{ color: statusColors.warning }}>
              No more classes to skip overall
            </span>
          )}
        </div>
      </div>

      {/* Per-Course Cards */}
      <div className="stats-grid">
        {courses.map((course) => (
          <CourseCard key={course.course_code} course={course} />
        ))}
      </div>
    </div>
  );
};

export default StatsDashboard;
