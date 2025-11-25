from django.db import models

# Create your models here.
class Employee(models.Model):
    class EmployeeStatusChoice(models.TextChoices):
        PENDING = 'pending', 'Pending'
        PROGRESS = 'in progress', 'In Progress'
        COMPLETED = 'completed', 'Completed'
    
    class DepartmentChoice(models.TextChoices):
        ENGINEERING = 'engineering','Engineering'
        HR = 'hr','HR'
        MARKETING = 'marketing', 'Marketing'

    employee_id = models.PositiveBigIntegerField(unique=True)
    employee_name = models.CharField(max_length=255, unique=True)
    department = models.CharField(default=DepartmentChoice.ENGINEERING, choices=DepartmentChoice.choices)
    task_id = models.PositiveBigIntegerField()
    task_name = models.CharField(max_length=255)
    hours_spent = models.PositiveBigIntegerField()
    deadline = models.DateField()
    status = models.CharField(default=EmployeeStatusChoice.PROGRESS, choices=EmployeeStatusChoice.choices)

    def __str__(self):
        return f'{self.pk} - {self.employee_name}'
