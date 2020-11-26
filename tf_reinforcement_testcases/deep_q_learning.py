# import time
from collections import deque

import numpy as np
import tensorflow as tf
from tensorflow import keras

import gym

from tf_reinforcement_testcases import models


class DQNAgent:
    NETWORKS = {'CartPole-v0': models.get_mlp,
                'CartPole-v1': models.get_mlp,
                'gym_halite:halite-v0': models.get_mlp}

    def __init__(self, env_name):
        self._train_env = gym.make(env_name)
        self._eval_env = gym.make(env_name)
        self._n_outputs = self._train_env.action_space.n
        input_shape = self._train_env.observation_space.shape
        self._model = DQNAgent.NETWORKS[env_name](input_shape, self._n_outputs)

        self._best_score = 0
        self._batch_size = 64
        self._discount_rate = tf.constant(0.95, dtype=tf.float32)
        self._optimizer = keras.optimizers.Adam(lr=1e-3)
        self._loss_fn = keras.losses.mean_squared_error
        self._replay_memory = deque(maxlen=40000)

        # collect some data with a random policy before training
        self._collect_steps(steps=4000, epsilon=1)

    def _epsilon_greedy_policy(self, obs, epsilon):
        if np.random.rand() < epsilon:
            return np.random.randint(self._n_outputs)
        else:
            Q_values = self._model(obs[np.newaxis])
            return np.argmax(Q_values[0])

    def _collect_one_step(self, obs, epsilon):
        action = self._epsilon_greedy_policy(obs, epsilon)
        next_obs, reward, done, info = self._train_env.step(action)
        self._replay_memory.append((obs, action, reward, next_obs, done))
        return next_obs, reward, done, info

    def _collect_steps(self, steps, epsilon):
        obs = self._train_env.reset()
        for _ in range(steps):
            obs, reward, done, info = self._collect_one_step(obs, epsilon)
            if done:
                obs = self._train_env.reset()

    def _sample_experiences(self, batch_size):
        indices = np.random.randint(len(self._replay_memory), size=batch_size)
        batch = [self._replay_memory[index] for index in indices]
        observations, actions, rewards, next_observations, dones = [
            np.array([experience[field_index] for experience in batch])
            for field_index in range(5)]
        return observations, actions, rewards, next_observations, dones.astype(int)

    def _evaluate_episode(self):
        obs = self._eval_env.reset()
        rewards = 0
        while True:
            # if epsilon=0, greedy is disabled
            action = self._epsilon_greedy_policy(obs, epsilon=0)
            obs, reward, done, info = self._eval_env.step(action)
            rewards += reward
            if done:
                break
        return rewards

    @tf.function
    def _training_step(self, discount_rate, n_outputs,
                       observations, actions, rewards, next_observations, dones,
                       ):
        next_Q_values = self._model(next_observations)
        max_next_Q_values = tf.reduce_max(next_Q_values, axis=1)
        target_Q_values = (rewards + (tf.constant(1.0) - dones) * discount_rate * max_next_Q_values)
        target_Q_values = tf.expand_dims(target_Q_values, -1)
        mask = tf.one_hot(actions, n_outputs, dtype=tf.float32)
        with tf.GradientTape() as tape:
            all_Q_values = self._model(observations)
            Q_values = tf.reduce_sum(all_Q_values * mask, axis=1, keepdims=True)
            loss = tf.reduce_mean(self._loss_fn(target_Q_values, Q_values))
        grads = tape.gradient(loss, self._model.trainable_variables)
        self._optimizer.apply_gradients(zip(grads, self._model.trainable_variables))

    def train(self):
        training_step = 0
        iterations_number = 10000
        eval_interval = 200

        obs = self._train_env.reset()
        for iteration in range(iterations_number):
            epsilon = max(1 - iteration / iterations_number, 0.01)
            # sample and train each step
            # collecting
            # t0 = time.time()
            obs, reward, done, info = self._collect_one_step(obs, epsilon)
            # t1 = time.time()
            # training
            # t2 = time.time()
            experiences = self._sample_experiences(self._batch_size)
            observations, actions, rewards, next_observations, dones = experiences

            observations = tf.convert_to_tensor(observations, dtype=tf.float32)
            actions = tf.convert_to_tensor(actions, dtype=tf.int32)
            rewards = tf.convert_to_tensor(rewards, dtype=tf.float32)
            next_observations = tf.convert_to_tensor(next_observations, dtype=tf.float32)
            dones = tf.convert_to_tensor(dones, dtype=tf.float32)
            experiences = observations, actions, rewards, next_observations, dones

            self._training_step(self._discount_rate, self._n_outputs, *experiences)
            training_step += 1
            # t3 = time.time()
            if done:
                obs = self._train_env.reset()

            if training_step % eval_interval == 0:
                episode_rewards = 0
                for episode_number in range(3):
                    episode_rewards += self._evaluate_episode()
                mean_episode_reward = episode_rewards / (episode_number + 1)

                if mean_episode_reward > self._best_score:
                    best_weights = self._model.get_weights()
                    self._best_score = mean_episode_reward
                # print("\rEpisode: {}, reward: {}, eps: {:.3f}".format(episode, mean_episode_reward, epsilon), end="")
                print("\rTraining step: {}, reward: {}, eps: {:.3f}".format(training_step,
                                                                            mean_episode_reward,
                                                                            epsilon))
                # print(f"Time spend for sampling is {t1 - t0}")
                # print(f"Time spend for training is {t3 - t2}")

        return self._model.set_weights(best_weights)
