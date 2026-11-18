from django.contrib import admin

from .models import Activity, Expense, ExpensePayer, ExpenseShare, Group, Membership, Settlement


class MembershipInline(admin.TabularInline):
    model = Membership
    extra = 0
    autocomplete_fields = ["user"]


@admin.register(Group)
class GroupAdmin(admin.ModelAdmin):
    list_display = ["name", "created_by", "created_at"]
    search_fields = ["name"]
    inlines = [MembershipInline]


@admin.register(Membership)
class MembershipAdmin(admin.ModelAdmin):
    list_display = ["group", "user", "joined_at"]
    list_filter = ["group"]


class ExpensePayerInline(admin.TabularInline):
    model = ExpensePayer
    extra = 0


class ExpenseShareInline(admin.TabularInline):
    model = ExpenseShare
    extra = 0


@admin.register(Expense)
class ExpenseAdmin(admin.ModelAdmin):
    list_display = [
        "description",
        "group",
        "date",
        "amount_cents",
        "category",
        "split_type",
        "created_by",
        "deleted_at",
    ]
    list_filter = ["group", "category", "split_type"]
    search_fields = ["description"]
    date_hierarchy = "date"
    inlines = [ExpensePayerInline, ExpenseShareInline]


@admin.register(Settlement)
class SettlementAdmin(admin.ModelAdmin):
    list_display = ["group", "from_user", "to_user", "amount_cents", "date", "deleted_at"]
    list_filter = ["group"]


@admin.register(Activity)
class ActivityAdmin(admin.ModelAdmin):
    list_display = ["created_at", "group", "actor", "verb", "target_type", "target_id"]
    list_filter = ["group", "verb", "target_type"]
    readonly_fields = ["created_at"]
