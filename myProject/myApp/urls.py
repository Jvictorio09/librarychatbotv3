from django.urls import path
from myApp import views
from django.contrib.auth.views import LogoutView
from django.contrib.auth import views as view


urlpatterns = [
    path('kaai', views.chat_page, name='chat_page'),
    path('chatbot_app/chat/', views.chat_api, name='chat_api'),
    path('upload-thesis/', views.upload_thesis_view, name='upload_thesis'),
    path('signup/', views.signup_view, name='signup'),
    path('', views.signin_view, name='login'),
    path('logout/', LogoutView.as_view(next_page='login'), name='logout'),

    path('password-reset/', views.password_reset_request, name='password_reset_custom'),
    path('password-reset/done/', views.password_reset_done, name='password_reset_done_custom'),
    path('reset/<uidb64>/<token>/', views.password_reset_confirm, name='password_reset_confirm_custom'),

  

    path('thesis-library/', views.thesis_library, name='thesis_library'),


    path('librarian/', views.librarian_home, name='librarian_home'),

    path('create-librarian/', views.create_librarian_view, name='create_librarian'),
    path('delete-theses/', views.delete_theses, name='delete_theses'),
    path("edit-thesis/", views.edit_thesis, name="edit_thesis"),
    path("search-theses/", views.search_theses, name="search_theses"),

    path('librarian/users/', views.librarian_users, name='librarian_users'),
    path('librarian/revoke/<int:user_id>/', views.revoke_user, name='revoke_user'),
    path('librarian/users/', views.librarian_users, name='librarian_users'),
    path('librarian/revoke/<int:user_id>/', views.revoke_user, name='revoke_user'),

    path("ajax/change-password/", views.ajax_change_password, name="ajax_change_password"),

    path("bulk-upload/", views.bulk_upload_page, name="bulk_upload"),
    path("bulk-upload/single/", views.bulk_upload_single, name="bulk_upload_single"),
]
