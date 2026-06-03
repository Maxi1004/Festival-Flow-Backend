import os
from io import BytesIO

import cloudinary
import cloudinary.uploader
from dotenv import load_dotenv

load_dotenv()


class CloudinaryUploadError(Exception):
    pass


def _configure_cloudinary() -> None:
    cloud_name = os.getenv("CLOUDINARY_CLOUD_NAME")
    api_key = os.getenv("CLOUDINARY_API_KEY")
    api_secret = os.getenv("CLOUDINARY_API_SECRET")

    if not cloud_name or not api_key or not api_secret:
        raise CloudinaryUploadError(
            "Cloudinary no esta configurado. Revisa las variables de entorno."
        )

    cloudinary.config(
        cloud_name=cloud_name,
        api_key=api_key,
        api_secret=api_secret,
        secure=True,
    )


def upload_talent_profile_photo(user_id: str, image_data: bytes) -> str:
    _configure_cloudinary()

    try:
        result = cloudinary.uploader.upload(
            BytesIO(image_data),
            folder=f"FestivalFlow/talents/{user_id}/profile",
            public_id="photo",
            overwrite=True,
            invalidate=True,
            resource_type="image",
        )
    except Exception as error:
        raise CloudinaryUploadError(
            "Cloudinary no pudo subir la foto de perfil. Intenta nuevamente."
        ) from error

    secure_url = result.get("secure_url")
    if not secure_url:
        raise CloudinaryUploadError(
            "Cloudinary no devolvio una URL segura para la foto de perfil."
        )

    return secure_url


def upload_producer_profile_photo(user_id: str, image_data: bytes) -> str:
    _configure_cloudinary()

    try:
        result = cloudinary.uploader.upload(
            BytesIO(image_data),
            folder=f"FestivalFlow/producers/{user_id}",
            public_id="profile-photo",
            overwrite=True,
            invalidate=True,
            resource_type="image",
        )
    except Exception as error:
        raise CloudinaryUploadError(
            "Cloudinary no pudo subir la foto de perfil. Intenta nuevamente."
        ) from error

    secure_url = result.get("secure_url")
    if not secure_url:
        raise CloudinaryUploadError(
            "Cloudinary no devolvio una URL segura para la foto de perfil."
        )

    return secure_url


def upload_talent_portfolio_pdf(user_id: str, pdf_data: bytes) -> str:
    _configure_cloudinary()

    try:
        result = cloudinary.uploader.upload(
            BytesIO(pdf_data),
            folder=f"FestivalFlow/talents/{user_id}/portfolio",
            public_id="portfolio.pdf",
            overwrite=True,
            invalidate=True,
            resource_type="raw",
        )
    except Exception as error:
        raise CloudinaryUploadError(
            "Cloudinary no pudo subir el PDF del portafolio. Intenta nuevamente."
        ) from error

    secure_url = result.get("secure_url")
    if not secure_url:
        raise CloudinaryUploadError(
            "Cloudinary no devolvio una URL segura para el PDF del portafolio."
        )

    return secure_url


def upload_project_team_chat_photo(project_id: str, image_data: bytes) -> str:
    _configure_cloudinary()

    try:
        result = cloudinary.uploader.upload(
            BytesIO(image_data),
            folder=f"FestivalFlow/projects/{project_id}/team-chat",
            public_id="group-photo",
            overwrite=True,
            invalidate=True,
            resource_type="image",
        )
    except Exception as error:
        raise CloudinaryUploadError(
            "Cloudinary no pudo subir la foto del grupo. Intenta nuevamente."
        ) from error

    secure_url = result.get("secure_url")
    if not secure_url:
        raise CloudinaryUploadError(
            "Cloudinary no devolvio una URL segura para la foto del grupo."
        )

    return secure_url
