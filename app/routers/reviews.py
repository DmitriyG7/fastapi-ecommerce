from fastapi import Depends, APIRouter, HTTPException, status
from app.db_depends import get_async_db
from app.models.reviews import Review as ReviewModel
from app.models.products import Product as ProductModel
from app.models.users import User as UserModel
from app.schemas import Review as ReviewSchema, ReviewCreate
from app.routers.products import update_product_rating

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import get_current_buyer, get_current_user_or_admin


router = APIRouter(
    prefix="/reviews",
    tags=["reviews"]
)

@router.get("/", response_model=list[ReviewSchema])
async def get_all_reviews(db: AsyncSession = Depends(get_async_db)):
    """
    Возвращает список всех активных отзывов
    """
    db_reviews = await db.scalars(select(ReviewModel).where(ReviewModel.is_active == True))
    return db_reviews.all()


@router.get("/products/{product_id}/reviews", response_model=list[ReviewSchema])
async def get_reviews_by_product(product_id: int, db: AsyncSession = Depends(get_async_db)):
    """
    Возвращает список активных отзывов по указанному продукту по его ID.
    """
    result = await db.scalars(select(ProductModel).where(ProductModel.id == product_id,
                                                             ProductModel.is_active == True))
    db_product = result.first()
    if not db_product:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Product not found or inactive")

    db_reviews = await db.scalars(select(ReviewModel).where(ReviewModel.product_id == product_id,
                                                            ReviewModel.is_active == True))
    return db_reviews.all()


@router.post("/", response_model=ReviewSchema, status_code=status.HTTP_201_CREATED)
async def create_review(review: ReviewCreate, db: AsyncSession = Depends(get_async_db),
                        current_user: UserModel = Depends(get_current_buyer)):
    """
    Создание отзыва
    """
    db_product = await db.scalar(select(ProductModel).where(ProductModel.id == review.product_id,
                                                            ProductModel.is_active == True))
    if not db_product:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Product not found or inactive")

    repeat_review = await db.scalar(select(ReviewModel).where(ReviewModel.user_id == current_user.id,
                                                               ReviewModel.product_id == review.product_id))
    if repeat_review:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="You have already left a review for this product")

    if db_product.seller_id == current_user.id:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="You can't leave a review for your product")

    new_review = ReviewModel(**review.model_dump(), user_id=current_user.id)
    db.add(new_review)
    await update_product_rating(db, db_product.id)
    await db.commit()
    await db.refresh(new_review)

    return new_review


@router.delete("/{review_id}")
async def delete_review(review_id: int, db: AsyncSession = Depends(get_async_db),
                        current_user: UserModel = Depends(get_current_user_or_admin)):
    """
    Мягкое удаление отзыва
    """
    db_review = await db.scalar(select(ReviewModel).where(ReviewModel.id == review_id,
                                                          ReviewModel.is_active == True))
    if not db_review:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Review not found or inactive")

    # Немного не понял как лучше реализовать проверку админа, поэтому пошёл по лёгкому пути
    # В schemas дописал, что можно роль админа поставить.
    if current_user.id != db_review.user_id and current_user.role != "admin":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Доступ запрещён")

    db_review.is_active = False
    await update_product_rating(db, db_review.product_id)
    await db.commit()

    return {"message": "Review deleted"}