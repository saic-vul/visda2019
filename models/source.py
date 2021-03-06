import tensorflow as tf

from .common import ClassificationLoss, run_balanced


class SourceTrainStep:
    def __init__(self, build_backbone_lambda, build_top_lambda, domains, learning_rate, batch_size):
        self.n_sources = len(domains) - 1
        self.domains = domains
        self.batch_size = batch_size
        self.iteration = tf.Variable(
            0, name='iteration', dtype=tf.int64, aggregation=tf.VariableAggregation.ONLY_FIRST_REPLICA
        )
        self.models = self._init_models(build_backbone_lambda, build_top_lambda)
        self.losses = self._init_losses()
        self.metrics = self._init_metrics()
        self.optimizers = self._init_optimizers(learning_rate)

    def train(self, batch):
        self.iteration.assign_add(1)

        with tf.GradientTape() as tape:
            source_predictions = run_balanced(
                models=(self.models['backbone'], self.models['top']),
                tensors=tuple(batch[i]['image'] for i in range(self.n_sources))
            )
            loss = self.losses['classification'](
                tuple(batch[i]['label'] for i in range(self.n_sources)), source_predictions
            )
            loss /= self.batch_size

        trainable_variables = self.models['backbone'].trainable_variables + self.models['top'].trainable_variables
        self.optimizers['optimizer'].apply_gradients(zip(
            tape.gradient(loss, trainable_variables), trainable_variables
        ))

        self.metrics['scce'].update_state(loss)
        target_top_features = self.models['backbone'](batch[-1]['image'], training=False)
        target_predictions = self.models['top'](target_top_features, training=False)
        self.metrics['target_acc'].update_state(batch[-1]['label'], target_predictions)
        for i in range(self.n_sources):
            self.metrics[f'{self.domains[i]}_acc'].update_state(batch[i]['label'], source_predictions[i])

    @staticmethod
    def _init_models(build_backbone_lambda, build_top_lambda):
        return {
            'backbone': build_backbone_lambda(),
            'top': build_top_lambda()
        }

    @staticmethod
    def _init_losses():
        return {
            'classification': ClassificationLoss()
        }

    def _init_metrics(self):
        metrics = {
            'scce': tf.keras.metrics.Mean(),
            'target_acc': tf.keras.metrics.SparseCategoricalAccuracy(),
        }
        for i in range(self.n_sources):
            metrics[f'{self.domains[i]}_acc'] = tf.keras.metrics.SparseCategoricalAccuracy()
        return metrics

    @staticmethod
    def _init_optimizers(learning_rate):
        return {
            'optimizer': tf.keras.optimizers.Adam(learning_rate)
        }


class SourceTestStep:
    def __init__(self, build_backbone_lambda, build_top_lambda):
        self.iteration = tf.Variable(0, name='iteration')
        self.models = self._init_models(build_backbone_lambda, build_top_lambda)
        self.metrics = self._init_metrics()

    @tf.function
    def test(self, batch):
        self.iteration.assign_add(1)

        predictions = []
        for image in batch['image']:
            features = self.models['backbone'](image, training=False)
            predictions.append(self.models['top'](features, training=False))
        predictions = tf.add_n(predictions) / len(predictions)
        self.metrics['acc'].update_state(batch['label'], predictions)
        return batch['path'], predictions

    @staticmethod
    def _init_models(build_backbone_lambda, build_model_lambda):
        return {
            'backbone': build_backbone_lambda(),
            'top': build_model_lambda()
        }

    @staticmethod
    def _init_metrics():
        return {
            'acc': tf.keras.metrics.SparseCategoricalAccuracy()
        }
