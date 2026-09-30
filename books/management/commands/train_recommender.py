from django.core.management.base import BaseCommand

from recommendations.training import TrainingConfig, train_recommender


class Command(BaseCommand):
    help = "Train and persist rankfmc recommender artifacts."

    def add_arguments(self, parser):
        parser.add_argument(
            "--factors",
            type=int,
            default=TrainingConfig.factors,
            help="Embedding dimensions for rankfmc model.",
        )
        parser.add_argument(
            "--epochs",
            type=int,
            default=TrainingConfig.epochs,
            help="Training epochs for rankfmc model.",
        )
        parser.add_argument(
            "--loss",
            type=str,
            default=TrainingConfig.loss,
            help="Ranking loss for rankfmc (e.g. warp).",
        )
        parser.add_argument(
            "--max-samples",
            type=int,
            default=TrainingConfig.max_samples,
            help="Negative samples per positive interaction.",
        )

    def handle(self, *args, **options):
        config = TrainingConfig(
            factors=options["factors"],
            epochs=options["epochs"],
            loss=options["loss"],
            max_samples=options["max_samples"],
        )
        result = train_recommender(config=config)
        if not result.get("trained"):
            reason = result.get("reason", "unknown")
            self.stdout.write(self.style.WARNING(f"Recommender training skipped: {reason}"))
            return
        self.stdout.write(
            self.style.SUCCESS(
                "Recommender training complete. "
                f"users={result['user_count']} "
                f"books={result['book_count']} "
                f"interactions={result['interaction_count']}"
            )
        )
