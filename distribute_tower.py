#  ====================================================
#   Filename: distribute_tower.py
#   Function: This file is used to save the tower model for multi-gpu
#   training.
#   1. It will deal with the net forward process
#   2. It will calculate the loss for multi-gpu tower
#   3. It will calculate the average gradient and update all models
#  ====================================================
import re
import tensorflow as tf

import distribute_constants as constants
import distribute_log as logger


class Tower():
    def __init__(self, net, scope, tower_grades, raw_data, ground_truth, loss_fn, optimizer):
        self.net = net
        self.scope = scope
        self.tower_grades = tower_grades
        self.raw_data = raw_data
        self.ground_truth = ground_truth
        self.loss_fn = loss_fn
        self.optimizer = optimizer

    def get_gradient(self, loss):
        return self.optimizer.compute_gradients(loss)

    def tower_loss(self):
        return self.__tower_loss()

    def process(self):
        # Calculate the loss for one tower of the net model. This function
        # constructs the entire net model but shares the variables across
        # all towers.
        loss, _ = self.tower_loss()
        # Reuse variables for the next tower.
        tf.get_variable_scope().reuse_variables()

        # Retain the summaries from the final tower.
        summaries = tf.get_collection(tf.GraphKeys.SUMMARIES, self.scope)

        # Calculate the gradients for the batch of data on this GMAN tower.
        grads = self.get_gradient(loss)

        # Keep track of the gradients across all towers.
        self.tower_grades.append(grads)
        return summaries, loss

    def __loss(self, result):
        """
        We need to realize the method to implement our own loss
        calculation. Ground_truth is saved in self, and we need to
        compare it with the output of the net.
        :param result: The result that we get from the model.
        :return: The loss value
        """
        return self.loss_fn(result, self.ground_truth)

    def loss_to_scope(self, result):
        loss = self.__loss(result)
        tf.add_to_collection('losses', loss)

        # The total loss is defined as the ms loss plus all of the weight
        # decay terms (L2 loss).
        return tf.add_n(tf.get_collection('losses'), name='total_loss')

    @staticmethod
    def average_gradients(tower_grads):
        """Calculate the average gradient for each shared variable across all towers.

         Note that this function provides a synchronization point across all towers.

         Args:
           tower_grads: List of lists of (gradient, variable) tuples. The outer list
             is over individual gradients. The inner list is over the gradient
             calculation for each tower.
         Returns:
            List of pairs of (gradient, variable) where the gradient has been averaged
            across all towers.
         """
        average_grads = []
        for grad_and_vars in zip(*tower_grads):
            # Note that each grad_and_vars looks like the following:
            #   ((grad0_gpu0, var0_gpu0), ... , (grad0_gpuN, var0_gpuN))
            grads = []
            for g, _ in grad_and_vars:
                # Add 0 dimension to the gradients to represent the tower.
                expanded_g = tf.expand_dims(g, 0)

                # Append on a 'tower' dimension which we will average over below.
                grads.append(expanded_g)

            # Average over the 'tower' dimension.
            grad = tf.concat(axis=0, values=grads)
            grad = tf.reduce_mean(grad, 0)

            # Keep in mind that the Variables are redundant because they are shared
            # across towers. So .. we will just return the first tower's pointer to
            # the Variable.
            v = grad_and_vars[0][1]
            grad_and_var = (grad, v)
            average_grads.append(grad_and_var)
        return average_grads

    def __tower_loss(self):
        """Calculate the total loss on a single tower running the DeHazeNet model.

              Args:
                scope: unique prefix string identifying the net tower, e.g. 'tower_0'
                images: Images. 3D tensor of shape [height, width, 3].

              Returns:
                 Tensor of shape [] containing the total loss for a batch of data
              """
        # Put data into designed CNN and get a result image batch
        logist = self.net.process(self.raw_data)
        # logist = inference(hazed_batch)
        # Build the portion of the Graph calculating the losses. Note that we will
        # assemble the total_loss using a custom function below.
        _ = Tower.loss_to_scope(self, logist)
        # Assemble all of the losses for the current tower only.
        losses = tf.get_collection('losses', self.scope)
        # Calculate the total loss for the current tower.
        total_loss = tf.add_n(losses, name='total_loss')

        # Attach a scalar summary to all individual losses and the total loss; do the
        # same for the averaged version of the losses.
        for l in losses + [total_loss]:
            # Remove 'tower_[0-9]/' from the name in case this is a multi-GPU training
            # session. This helps the clarity of presentation on tensorboard.
            loss_name = re.sub('%s_[0-9]*/' % constants.TOWER_NAME, '', l.op.name)
            tf.summary.scalar(loss_name, l)
        return total_loss, logist

    @staticmethod
    def tower_fn(tower):
        return tower.process()

if __name__ == '__main__':
    pass
