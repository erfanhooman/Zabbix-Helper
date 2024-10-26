from backend.messages import mt
from backend.utils import create_response
from django.contrib.auth import authenticate
from drf_yasg import openapi
from drf_yasg.utils import swagger_auto_schema
from rest_framework import status
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.views import APIView
from rest_framework_simplejwt.tokens import RefreshToken, AccessToken

from .models import UserSystem
from .serializers import SignupSerializer, LoginSerializer, UpdateZabbixSettingsSerializer


class SignupView(APIView):
    permission_classes = [AllowAny]

    @swagger_auto_schema(
        operation_summary="Signup",
        operation_description="Sign up to monitor your system.",
        request_body=SignupSerializer,
        responses={
            200: openapi.Response(
                description="Sign up successfully",
                examples={
                    "application/json": {
                        "success": True,
                        "message": "user created, successfully",
                        "data": {
                            "username": "system username that set for monitoring system",
                            "password": "system password that set for monitoring system",
                            "zabbix_server_url": "server url for remote access",
                            "zabbix_host_name": "zabbix host name set for the remote one",
                            "zabbix_username": "zabbix username",
                            "zabbix_password": "zabbix password"
                        }
                    }
                }
            ),
            400: openapi.Response(
                description="Bad Request",
                examples={
                    "application/json": {
                        "success": False,
                        "message": "The Reason of the Error",
                        "data": {
                            "field with problem": [
                                "the problem of it"
                            ]
                        }
                    }
                }
            )
        }
    )
    def post(self, request):
        serializer = SignupSerializer(data=request.data)
        if serializer.is_valid():
            serializer.save()
            return create_response(success=True, status=status.HTTP_201_CREATED, message=mt[201],
                                   data=serializer.validated_data)
        return create_response(success=False, status=status.HTTP_400_BAD_REQUEST, message=mt[404],
                               data=serializer.errors)


class LoginUserView(APIView):
    permission_classes = [AllowAny]

    @swagger_auto_schema(
        operation_summary="Login",
        operation_description="Login and get the Token",
        request_body=LoginSerializer,
        responses={
            200: openapi.Response(
                description="login successfully",
                examples={
                    "application/json": {
                        "success": True,
                        "message": "user logged in, successfully",
                        "data": {
                            "access": "access token (life time: 60min)",
                            "refresh": "refresh token (life time: 30days)"
                        }
                    }
                }
            ),
            400: openapi.Response(
                description="Bad Request",
                examples={
                    "application/json": {
                        "success": False,
                        "message": "The Reason of the Error"
                    }
                }
            )
        }
    )
    def post(self, request):
        serializer = LoginSerializer(data=request.data)
        if serializer.is_valid():
            username = serializer.validated_data['username']
            password = serializer.validated_data['password']
            user = authenticate(username=username, password=password)
            if user:
                data = {
                    "refresh": str(RefreshToken.for_user(user)),
                    "access": str(AccessToken.for_user(user))
                }
                return create_response(success=True, status=status.HTTP_200_OK, data=data)
            return create_response(success=False, status=status.HTTP_401_UNAUTHORIZED, message=mt[431])
        return create_response(status=status.HTTP_401_UNAUTHORIZED, success=False, data=serializer.errors)


class UpdateZabbixSettingsView(APIView):
    permission_classes = [IsAuthenticated]

    @swagger_auto_schema(
        operation_summary="Update Zabbix Settings",
        operation_description="Update your Zabbix monitoring settings.",
        request_body=UpdateZabbixSettingsSerializer,
        responses={
            200: openapi.Response(
                description="Zabbix settings updated successfully",
                examples={
                    "application/json": {
                        "success": True,
                        "message": "Zabbix settings updated successfully.",
                        "data": {
                            "zabbix_server_url": "https://your-zabbix-server-url.com",
                            "zabbix_username": "new_username",
                            "zabbix_password": "new_password",
                            "zabbix_host_name": "new_host_name"
                        }
                    }
                }
            ),
            400: openapi.Response(
                description="Invalid input data",
                examples={
                    "application/json": {
                        "success": False,
                        "message": "The reason for the error",
                        "data": {
                            "field_with_issue": [
                                "error description"
                            ]
                        }
                    }
                }
            ),
            401: openapi.Response(
                description="Unauthorized - UserSystem settings not found or invalid credentials",
                examples={
                    "application/json": {
                        "success": False,
                        "message": "UserSystem settings not found."
                    }
                }
            )
        }
    )
    def post(self, request):
        user = request.user
        user_system = UserSystem.objects.filter(user=user).first()

        if not user_system:
            return create_response(success=False, status=status.HTTP_401_UNAUTHORIZED, message=mt[430])

        serializer = UpdateZabbixSettingsSerializer(user_system, data=request.data)

        if serializer.is_valid():
            serializer.save()
            return create_response(success=True, status=status.HTTP_200_OK, data=serializer.validated_data,
                                   message=mt[200])

        return create_response(success=False, status=status.HTTP_400_BAD_REQUEST, data=serializer.errors,
                               message=mt[404])
