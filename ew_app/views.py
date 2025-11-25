from django.shortcuts import render
from django.http import HttpResponse
from django.utils import timezone
from django.db import transaction
from django.db.models import Sum, Count, Q, F, ExpressionWrapper, FloatField, Avg
from django.db.models.functions import TruncWeek
from rest_framework.viewsets import ModelViewSet
from rest_framework.response import Response
from rest_framework import status
from rest_framework.decorators import action
import csv
from io import StringIO, BytesIO
import base64
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from .models import Employee
from .serializers import EmployeeSerializer

# Create your views here.


class EmployeeViewset(ModelViewSet):
    queryset = Employee.objects.all()
    serializer_class = EmployeeSerializer

    def custom_exception(self, e):
        return Response({'error':str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
    
    def convert_row_value_lower(self, value:str)->str:
        try:
            return value.lower()
        except Exception as e:
            raise e
    
    def validate_csv_data(self, reader):
        """
        Validate CSV rows and check duplicates in one pass.
        Returns:
            valid_rows: list of validated, unique rows for bulk insert
            errors: list of row-specific errors
        """
        errors = []
        valid_rows = []

        seen_employee_ids = set()
        seen_employee_names = set()
        seen_task_keys = set()

        for row_num, row in enumerate(reader, start=1):
            # Normalize values
            row['status'] = self.convert_row_value_lower(row.get('status', ''))
            row['department'] = self.convert_row_value_lower(row.get('department', ''))

            serializer = EmployeeSerializer(data=row)
            if not serializer.is_valid():
                errors.append({"row": row_num, "errors": serializer.errors, "data": row})
                continue

            data = serializer.validated_data
            emp_id = data['employee_id']
            emp_name = data['employee_name']
            task_key = (data['employee_id'], data['task_id'])

            duplicate_error = False
            if emp_id in seen_employee_ids:
                errors.append({"row": row_num, "errors": f"Duplicate employee_id {emp_id}", "data": row})
                duplicate_error = True
            if emp_name in seen_employee_names:
                errors.append({"row": row_num, "errors": f"Duplicate employee_name {emp_name}", "data": row})
                duplicate_error = True
            if task_key in seen_task_keys:
                errors.append({"row": row_num, "errors": f"Duplicate task_id for employee {emp_id}", "data": row})
                duplicate_error = True

            if duplicate_error:
                continue


            seen_employee_ids.add(emp_id)
            seen_employee_names.add(emp_name)
            seen_task_keys.add(task_key)
            valid_rows.append(data)

        return valid_rows, errors
    
    def render_chart_image(self, labels, values, title="", kind="bar"):
        try:
            """Return HttpResponse with PNG chart"""
            fig, ax = plt.subplots(figsize=(6, 4))
            if kind == "bar":
                ax.bar(labels, values, color='skyblue')
                ax.set_ylabel("Hours / Count")
            elif kind == "line":
                ax.plot(labels, values, marker='o', color='skyblue')
                ax.set_ylabel("Count")
            elif kind == "pie":
                ax.pie(values, labels=labels, autopct="%1.1f%%")
            elif kind == "table":
                ax.axis("off")
                table_data = values
                headers = labels     
                table = ax.table(cellText=table_data, colLabels=headers, cellLoc="center", loc="center")
                table.auto_set_font_size(False)
                table.set_fontsize(10)
                table.scale(1, 2)
            else:
                ax.plot(labels, values)

            ax.set_title(title)
            plt.xticks(rotation=45, ha='right')

            buffer = BytesIO()
            plt.tight_layout()
            plt.savefig(buffer, format="png")
            plt.close(fig)
            buffer.seek(0)
            return HttpResponse(buffer.getvalue(), content_type="image/png")
        except Exception as e:
            raise Exception(e)

    def create(self, request, *args, **kwds):
        try:
            with transaction.atomic():
                file = request.FILES.get("file")
                if not file:
                    return Response({"error": "No file uploaded"}, status=status.HTTP_400_BAD_REQUEST)

                csv_text = file.read().decode("utf-8")
                io_string = StringIO(csv_text)
                reader = csv.DictReader(io_string)

                valid_rows, errors = self.validate_csv_data(reader)
                if errors:
                    transaction.set_rollback(True)
                    return Response({
                        "status": "failed",
                        "errors": errors
                    }, status=status.HTTP_400_BAD_REQUEST)


                Employee.objects.bulk_create(
                    [Employee(**data) for data in valid_rows],
                    ignore_conflicts=True
                )

                return Response({
                    "status": "success",
                    "inserted": len(valid_rows)
                }, status=status.HTTP_201_CREATED)
                    
        except Exception as e:
            return self.custom_exception(e)
    
    @action(detail=False, methods=["get"], url_path="department-contribute-hour")
    def get_active_users(self, request):
        try:
            data = Employee.objects.values("department").annotate(total_hours=Sum('hours_spent')).order_by('department')

            if request.query_params.get("chart", "false").lower() == "true":
                labels = [d["department"] for d in data]
                values = [d["total_hours"] for d in data]
                return self.render_chart_image(labels, values, title="Hours per Department", kind="bar")
            return Response({'result':data}, status=status.HTTP_200_OK)
        except Exception as e:
            self.custom_exception(e)

    @action(detail=False, methods=["get"], url_path="workload-employee")
    def get_workload_employee(self, request):
        try:
            highest_person_list_count = int(request.query_params.get('limit', 3))
            data = Employee.objects.values("employee_name").annotate(total_hours=Sum("hours_spent"),
                pending_tasks=Count("id", filter=Q(status__in=[
                    Employee.EmployeeStatusChoice.PENDING,
                    Employee.EmployeeStatusChoice.PROGRESS
                ])))\
            .order_by("-total_hours")[:highest_person_list_count]

            if request.query_params.get("chart", "false").lower() == "true":
                table_labels = ["Employee", "Total Hours", "Pending Tasks"]
                table_values = [(d["employee_name"], d["total_hours"], d["pending_tasks"]) for d in data]

                return self.render_chart_image(
                    labels=table_labels,
                    values=table_values,
                    title="Top Employees Workload & Pending Tasks",
                    kind="table"
                )


            return Response({'result':data}, status=status.HTTP_200_OK)
        except Exception as e:
            self.custom_exception(e)

    @action(detail=False, methods=["get"], url_path="employee-task-completion")
    def get_employee_task_completion(self, request):
        try:
            '''
            employee_datas = Employee.objects.all()
            department_stats = {}
            for emp in employee_datas:
                dept = emp.department
                if dept not in department_stats:
                    department_stats[dept] = {
                        "total": 0,
                        "completed": 0,
                    }
                department_stats[dept]["total"] += 1
                if emp.status == Employee.EmployeeStatusChoice.COMPLETED:
                    department_stats[dept]["completed"] += 1
            result = [
                {
                    "department": dept,
                    "total_tasks": stats["total"],
                    "completed_tasks": stats["completed"],
                    "completion_percentage": round(
                        (stats["completed"] / stats["total"]) * 100
                        if stats["total"] > 0 else 0,
                        2
                    )
                }
                for dept, stats in department_stats.items()
            ]
            '''

            data = Employee.objects.values("department")\
            .annotate(
                total_tasks=Count("id"),
                completed_tasks=Count("id", filter=Q(status=Employee.EmployeeStatusChoice.COMPLETED)),
                completion_percentage=ExpressionWrapper(
                    (Count("id", filter=Q(status=Employee.EmployeeStatusChoice.COMPLETED)) * 100.0) 
                    / Count("id"),
                    output_field=FloatField()
                )
            )

            if request.query_params.get("chart", "false").lower() == "true":
                labels = [d["department"] for d in data]
                values = [round(d["completion_percentage"], 2) for d in data]

                return self.render_chart_image(labels, values, title="Task Completion % per Dept", kind="pie")


            return Response({'result':data}, status=status.HTTP_200_OK)

        except Exception as e:
            return self.custom_exception(e)
    
    @action(detail=False, methods=["get"], url_path="delay-task")
    def get_delay_task(self, request):
        try:
            today = timezone.now().date()

            queryset = Employee.objects.filter(
                Q(deadline__lt=today) &
                ~Q(status=Employee.EmployeeStatusChoice.COMPLETED)
            )

            if request.query_params.get("chart", "false").lower() == "true":
                employee_data = queryset.values('employee_name').annotate(
                    total_hours=Sum('hours_spent')
                ).order_by('employee_name')

                labels = [d['employee_name'] for d in employee_data]
                values = [d['total_hours'] for d in employee_data]

                return self.render_chart_image(
                    labels=labels,
                    values=values,
                    title="Delayed Tasks - Hours Spent per Employee",
                    kind="line"
                )
            data = queryset.values().order_by('employee_name')
            return Response({'result':data}, status=status.HTTP_200_OK)
        except Exception as e:
            self.custom_exception(e)
    
    @action(detail=False, methods=["get"], url_path="task-complete-hour")
    def get_average_hours(self, request):
        try:
            data = Employee.objects.filter(status=Employee.EmployeeStatusChoice.COMPLETED)\
            .values("employee_id", "employee_name","task_id", "task_name")\
            .annotate(avg_hours=Avg("hours_spent"))
            return Response({'result':data}, status=status.HTTP_200_OK)
        except Exception as e:
            self.custom_exception(e)